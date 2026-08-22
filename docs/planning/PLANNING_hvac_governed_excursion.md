# PLANNING — Governed Thermostat Excursion Primitive (D2 + D3) — REV 6

**Card:** `HVAC-GOVERNED-EXCURSION-1`
**Tier:** **3** — delicate shared-primitive; invariant-critical; cost + comfort ripple; Bug Class #53 (one missed site defeats the guarantee).
**Scope of this document:** D2 (primitive) + D3 (migration). D1 (observability columns on `ac_ramp_events` + settled callback) already shipped v5.86.0 and is an INPUT.

**Scope decisions (locked, do NOT relitigate):**
- Mode axis is OUT for six of seven excursion kinds. **Egress is the ONE exception** — its action IS a mode change; see §5 and §9.
- S14 (duty off-phase ceiling) is EXCLUDED — deliberate indefinite hold, documented at `PLANNING_preset_flap_offphase_honesty.md:184-195,:280`, protected by shipped test `test_ceiling_held_until_next_preset_transition`. See §12 parked-plan-trigger.
- `hard_reset_preset_assert` is NOT a primitive-managed kind. One-line `emit_set_preset_mode(snapshot_preset)` in `_verify_restore`'s success branch (`hvac_override.py:2913-2917`) instead. `EXCURSION_KIND_hard_reset_preset_assert` MUST NOT exist so it cannot be wired by analogy later.
- **The excursion is UNOPINIONATED about intent.** It snapshots what it finds at `begin()` and restores exactly that at `return()`. It does not decide what SHOULD be there. Rev-3's "stamp what S1 emits" apparatus is DELETED — the excursion never asks the question the stamp existed to answer. Policy about "should this manual survive?" lives in the arrester + preset-manager, which have the grace, provenance, and midpoint logic the restore has none of. See §4.3.
- **The excursion holds an EXPLICIT LEASE on its zone for its duration.** Decision ticks defer because an active `hvac_excursion_state` row exists, NOT because the thermostat reads `manual`. This is the mechanism by which snapshot-restore stays safe once HVAC-MANUAL-PRESET-CONTRACT-1 removes the accidental manual-based lockout that today silently protects excursions. See §4.4.

> ## ⚠️ REV-6 — THE LEASE GATE IS STRIPPED (operator decision, 2026-08-21)
>
> **Four Tier-3 reviews returned DO-NOT-SHIP.** All four independently found that the lease
> creates **a suppression with no reliable discharge** — leases leak on early-exit paths, leases
> rehydrated at boot are orphaned by construction (no owner can release them), the expiry sweep
> only runs on a path most ticks never reach, and the kill switch is begin-only so it cannot
> discharge a stuck lease. Because the gate dropped preset writes, each leak silently removed ALL
> preset governance from a zone for up to 2 hours — including load-shed forced-away, which Review B
> verified DOES route through the gated path despite the plan's claim that safety paths do not.
>
> Review D's summary is the one to remember: *a stuck lease with no manual escape is worse than the
> accidental lockout it replaced.*
>
> **DECISION: strip the lease GATE; keep the snapshot/restore machinery.** The reasoning is
> marginal-benefit, not defect-count. The lease exists to protect excursions ONCE
> `HVAC-MANUAL-PRESET-CONTRACT-1` removes the accidental `manual`-based lockout that protects them
> TODAY. That cycle has not landed, so **the lease's value is currently zero while its risk is
> measured.** Building it now pays the risk before the benefit exists.
>
> REMOVED: the gate at `hvac.py:2009-2027`, `lease_active()` as a consumed API, and the
> gate-derived `stuck_excursion_lease` alert semantics. KEPT: `begin_excursion`/`return_excursion`,
> the snapshot, persistence, boot audit, kill switch, and all 11 site migrations — that is the
> cycle's actual value and it stands on its own.
>
> **PARKED-PLAN TRIGGER — read this carefully before rebuilding the lease.** Operator: *"when we
> get to the other thing, take another look after the shape has changed."* That is NOT approval to
> build the lease as designed here. It means: when `HVAC-MANUAL-PRESET-CONTRACT-1` is scoped,
> **re-derive the exclusion mechanism from scratch against whatever the shape is THEN.** That cycle
> is expected to collapse five partial preset-decision owners into one decider (see the card's
> `ARCHITECTURAL_REFRAME_2026_08_21_DECIDER_VS_WRITER`) — and a single decider may not need a lease
> at all, or may need a different mechanism entirely. Rev-5's design is EVIDENCE of what went
> wrong, not a blueprint to resume from. Anyone who reads this section as "the lease is pre-approved
> for the next cycle" has misread it.
>
> Also verified live during review and worth carrying forward: `manual` IS present in `preset_modes`
> on all three Bryant thermostats, so the unopinionated snapshot-restore writing `manual` back is
> legal on this hardware. A Review B concern, refuted by measurement.

**Rev-5 changes vs rev-4 (ONE change, and it is a correctness fix):**
- **THE LEASE CHECK MOVES from the consult to the emit merge point.** Rev-4 placed it "immediately before `should_change_preset`". That placement is WRONG and would have shipped a hole: the vacancy branch at `hvac.py:1892-1894` (`# Bypass should_change_preset() manual guard for vacancy (RH3 fix)`) takes the `if` arm and NEVER REACHES the consult. Both arms then converge on the same emit at `hvac.py:2013`. A vacancy sweep would therefore write `away` straight through an active excursion while `lease_active` reported clean — a silent Bug-Class-#53 miss of exactly the kind this cycle exists to prevent. **Gate the WRITE, not the CONSULT.** §4.4 and AC14 rewritten; AC14 gains a second mandatory test that drives the vacancy arm specifically.
- **Preset emit sites enumerated: FOUR, not one** — `hvac.py:2013`, `hvac_override.py:2554`, `hvac_override.py:3258`, `hvac_egress.py:677`. Any "the preset write" phrasing is a bug in the plan. See §3.
- **Provenance of this finding:** operator reframe 2026-08-21 (decider-vs-writer). Recorded because it is the second time a single-site mental model nearly defeated a completeness pass — see `HVAC-MANUAL-PRESET-CONTRACT-1 / ARCHITECTURAL_REFRAME_2026_08_21_DECIDER_VS_WRITER`.

**Rev-4 changes vs rev-3:**
- **Snapshot-restore replaces stamp-restore.** §4.3 rewritten. `ZoneState.last_intended_preset` field, the S1 stamp write, `resolve_intended_preset` mentions, AC13, and non-goal 12's rev-3 framing all removed. Simplification, not loss — the excursion never induces a preset it did not find, so the self-disarm defect dissolves (pre_preset='manual' → snapshot='manual' → restore='manual'; nothing to get stuck in).
- **Explicit lease added.** New §4.4. The lease token IS the persisted `hvac_excursion_state` row — no new machinery. Two module constants (`EXCURSION_LEASE_SLACK_S`, `EXCURSION_LEASE_MAX_S`) added to §6. Cross-cycle interaction with HVAC-MANUAL-PRESET-CONTRACT-1 called out in §1 and §11.
- **§13.5 CLOSED by operator ruling** — no longer an open decision.

**Prior rev-2/rev-3 notes preserved:** §11 pushbacks DECIDED (§10). §12 parked-plan-trigger for HVAC-PRESET-FLAP-1. §3 and §5 merged. AC1/AC2/AC3/AC7 rewritten. Return-sequence failure table. Kill-switch begin-only. 15-row site table.

---

## 1. Falsifiable invariant + discriminator (rev-4: snapshot-restore + lease)

> **INVARIANT:** After any primitive-managed excursion terminates by any means —
> normal completion, gate-defer at `begin()`, service-call exception, cancellation,
> coordinator teardown, or Home Assistant restart — the zone's `preset_mode` and
> setpoints observed at the thermostat equal the SNAPSHOT taken at `begin()` (as
> stored on the `hvac_excursion_state` row — see §4.3) within
> `EXCURSION_SETTLE_WINDOW_S`. Concretely:
>
> - A persisted `hvac_excursion_state` row exists from `begin()` returning a token
>   until `return_excursion()` acks OR the boot audit drops it by guard.
> - `return_excursion()` emits, IN THIS ORDER, EACH AWAITED WITH `blocking=True`:
>   (a) `emit_set_temperature(pre_target_low, pre_target_high, blocking=True)` →
>   (b) `emit_set_preset_mode(pre_preset, blocking=True)` iff `pre_preset` is not None →
>   (c) optional `set_hvac_mode` re-assert (only for `kind=egress_pause` with `intended_mode=<saved pre-pause mode>`, OR when `intended_mode == "heat_cool"` and drifted for other kinds) →
>   (d) THEN the D1 `restore_ok_immediate` read fires (post step c).
> - After `EXCURSION_SETTLE_WINDOW_S`, thermostat state equals snapshot OR a
>   `restore_ok=False` row is written naming the divergence.
>
> **The excursion does not resolve intent.** It has no opinion about what SHOULD
> be on the wire — only about what WAS on the wire before it perturbed things. If
> the snapshot at `begin()` was `manual`, the restore is `manual`. Policy about
> whether that `manual` should be respected or overwritten lives in the arrester
> and the preset manager, which have grace, provenance, and midpoint logic; the
> excursion has none of those and must not pretend to.

**Falsification obligations for framing D (each requires a concrete legal-config
reachable repro or refute):**

1. A code path where `begin()` writes the DB AFTER the service call (persist-after-actuate; egress today has this — see §5.15).
2. A raw `set_temperature` / `set_preset_mode` bypass — REFUTED zero-bypass per Reviewer A §1.3; framing D may re-verify.
3. Any legal config where `return_excursion` emits a preset that DIFFERS from the `pre_preset` field on the row (except the explicit "pre_preset is None → skip step (b)" case) — this is the whole point of snapshot-restore and D must attack it.
4. A service-call ordering under which the preset write lands BEFORE the setpoint (the 509 ms clobber pattern) — CONTRADICTED by `blocking=True` awaited sequence; D must confirm the contract holds at every migration row.
5. A teardown path (config-entry unload, coordinator shutdown, options reload) that leaves a live excursion row untended by the boot audit.
6. A kill-switch flip mid-flight that strands a persisted row (the plan resolves this by making the switch begin-only; D verifies).
7. **A decision tick that WRITES the wire (S1 preset apply, S10 DPM apply, or any migrated START) while an unexpired lease is active on the same zone.** Under the fix, the tick defers via §4.4. Under a lease-miss defect, the tick writes over the excursion's snapshot mid-flight.
8. **A stale/stuck lease that a tick would defer to indefinitely.** The lease MUST have visible, time-bounded expiry (§4.4 + §6); an unbounded lease is the accidental-manual-lockout defect re-created in explicit form.

### 1.1 Three defect signatures (all in the discriminator table, all must be caught)

| Shape | Cause | AC that catches it |
|---|---|---|
| `restore_ok_immediate=1 AND restore_ok=0` | Late cloud-poll clobber landing after the read (the original 509 ms defect) | AC1a |
| `restore_ok_immediate=0 AND restore_ok=0` | Non-blocking preset write hadn't landed at the immediate read AND never settled (BP-2 — the observed live shape not previously covered) | AC1b |
| `preset_before='manual' AND restore_ok IS NULL` on the `nudge_started` row | Self-disarm (pre-fix): observed-state snapshot filtered to nothing → no restore attempted. **Under rev-4 snapshot-restore, this shape is DISSOLVED at source** — `pre_preset='manual'` yields `restore_preset='manual'`, an equality check the settled callback records as `restore_ok=1`. | AC3 |

Under the fix, ALL THREE must go to zero for URA-initiated excursions.

### 1.2 Why the lease matters beyond this cycle (load-bearing, per operator)

URA today decouples governance from vendor thermostat state by ACCIDENT. A soft-nudge
issues a raw `set_temperature`; Carrier/Bryant flips `preset_mode` to `manual` as a
side effect; every subsequent decision tick's preset-apply path
(`should_change_preset` at `hvac_preset.py:202-217`) returns False because
`preset_mode == "manual"`; and so no tick clobbers the in-flight excursion. This
works, but the "hands-off" signal it relies on is **a preset value URA induced
itself via a setpoint write**, then treated as authoritative operator intent. The
same mechanism is what produces the 14-hour stuck-manual blocks, the self-disarm
latch, and the observation that ticks "just happen not to fight" excursions.

The explicit lease (§4.4) replaces the accidental, invisible, permanent lock with
an explicit, visible, expiring one. Once HVAC-MANUAL-PRESET-CONTRACT-1 unblocks
ticks during `manual` — which is the whole point of that card — snapshot-restore
becomes genuinely unsafe WITHOUT the lease, because ticks that used to defer on
`preset_mode == "manual"` will start racing excursions. The lease MUST land in the
same cycle as snapshot-restore or the sequencing is unsafe.

---

## 2. Institutional context verified (rev-4 changes in **bold**)

### 2.1 Files read end-to-end for rev 4

- `hvac_setpoint.py` (222 lines, full).
- `hvac_override.py`: 2380-2570 (compromise), 2760-2925 (hard reset + `_verify_restore`), 3055-3350 (nudge lifecycle), 3860-4200 (cancel + startup audit — `async def async_startup_ramp_audit` at `:4057`).
- `hvac_egress.py` 515-685.
- `hvac.py` 1955-1990 (S1 emit), 1530-1749 (reason-ladder region — verified non-pure; basis for rev-3's extraction rejection, still relevant to rev-4's non-goal 12).
- `hvac.py` 2240-2310 (S10 DPM apply).
- **`hvac_preset.py:202-217` (`should_change_preset` — the accidental `manual`-based lockout).** Basis for §1.2 concurrency analysis.
- Reviewer A + B reports treated as authoritative for lines/quotes I did not personally re-open — they cited source with quotes; converged independently.
- `docs/planning/PLANNING_preset_flap_offphase_honesty.md:184-195, :280` — S14 deliberate-hold documentation (§12).
- `docs/planning/AUDIT_restart_safety_classification.md:1-100` — restart doctrine + AC-ramp exemplar refutation.

### 2.2 REUSED (rev-4: stamp row removed; snapshot row present)

| Proposed capability | REUSED existing | File:line |
|---|---|---|
| Setpoint chokepoint (freeze + deadband + comfort gate) | `emit_set_temperature`, `apply_setpoint_guards` | `hvac_setpoint.py:48, 121` |
| Preset chokepoint | `emit_set_preset_mode` | `hvac_setpoint.py:180` |
| Per-zone persisted in-flight excursion row (nudge exemplar) | `ac_reset_state.in_flight_nudge_*` + `set_ac_in_flight_nudge` / `get_zones_with_in_flight_nudge` / `clear_ac_in_flight_nudge` | `database.py:1439`; `hvac_override.py:3074-3079, 3142, 3873, 4070, 4109` |
| Pre-preset observed-state snapshot (the exemplar of snapshot-restore, filtered today; rev-4 keeps the snapshot mechanism and DROPS the filter — see §13.5) | `_nudge_pre_preset` + comment at `hvac_override.py:3107-3112` | `hvac_override.py:3086-3112, 3244-3273` |
| Restart-safe restore-on-boot (the EXEMPLAR — do NOT rewrite) | `async_startup_ramp_audit` | `hvac_override.py:4057` |
| Second post-restart reconciler (banking orphan scan, one-shot per process) | `_first_eval_done` orphan scan calling `_release_banked_zones` | `hvac_predict.py:508-536` — Reviewer A-HIGH-3 |
| Egress pause persistence (THIRD in-flight-excursion table) | `_db_save_paused_full` | `hvac_egress.py:592` — Reviewer A-HIGH-3 |
| D1 shipped telemetry columns | `preset_before/after`, `mode_before/after`, `restore_ok`, `restore_ok_immediate` on `ac_ramp_events` | `database.py:1519-1524, 1633-1638, 7419-7444`; site `hvac_override.py:3091-3104, 3175-3177, 3281-3328` (v5.86.0) |
| Settle-window constant (D1-shipped) | `AC_NUDGE_RESTORE_SETTLE_DELAY_S = 12` | `hvac_const.py:571`; consumed `hvac_override.py:3390` |
| Comfort-delay ALLOW/DEFER | `OverrideArrester.comfort_delay_active` | `hvac_override.py:1498` |
| Suppress-then-emit / unsuppress-on-defer (begin path) | A-MED-2 discipline | `hvac.py:2258, 2286-2294`; `hvac_override.py:3135, 3878, 4162` |
| Suppress-BEFORE-emit (return path — deliberately opposite; do not invert) | Nudge restore re-suppresses before writing — comment at `hvac_override.py:3215-3217` | `hvac_override.py:3218, 3254` (Reviewer B M-3) |
| R1 ordering (DB before service call) — the property being generalised | Comment block | `hvac_override.py:3055-3062, 3072-3079` |
| Refuse raw `climate.*` writes | `_CLIMATE_BLOCKED_SERVICES` guard | `coordinator.py:1018-1050` |
| Verify-and-retry ladder (mode axis, hard reset) — exemplar we deliberately do NOT copy verbatim | `_verify_restore` | `hvac_override.py:2860-2925` |
| Switch persistence pattern (correct machinery for kill switch) | Sibling off-phase kill switch — RestoreEntity + `async_added_to_hass` + coordinator kwarg seeding | `switch.py:5993-6083`; `hvac.py:317-319`; `hvac.py:617-625` |
| S13 return needs to write `_last_emitted_range` or DPM throttle re-strands it | DPM throttle | `hvac.py:2252-2255` |
| Banking baseline resolver (avoids the ratchet on re-snapshot) | `_resolve_baseline_range` | `hvac_predict.py:842` |
| **The accidental lockout the lease replaces** | **`should_change_preset` returning False when `preset_mode == "manual"`** | **`hvac_preset.py:202-217`** (basis for §1.2 + §4.4) |

### 2.3 NEW (rev-4: stamp row removed; lease knobs added)

| Proposed | Why NEW |
|---|---|
| `hvac_excursion_state` table (per-zone; PK `zone_id`; columns per §4.5) | No existing table models a generic excursion across ≥5 kinds. `ac_reset_state` stays authoritative for the nudge daily counter. |
| `hvac_excursion_events` table — carries **non-nudge kinds only** | Cross-kind analytics needs one landing table for non-nudge; nudge stays where D1 put it. No dual-write. |
| New nullable column `excursion_id TEXT` on `ac_ramp_events` | Enables UNION analytics without dual-write. |
| `hvac_excursion.py` module — `begin_excursion(...) → ExcursionToken \| None`, `return_excursion(...) → ReturnOutcome`, `async_startup_excursion_audit()`, `lease_active(zone_id) → bool` | Named API; no equivalent exists. Chokepoints (`emit_*`) are NOT replaced. **No resolver, no stamp — the excursion does not resolve intent.** |
| `EXCURSION_KIND` — a `StrEnum`: `NUDGE`, `COMPROMISE`, `BANKING`, `PREHEAT`, `EGRESS_PAUSE` | Five kinds. `HARD_RESET_PRESET_ASSERT` deliberately NOT included. |
| Constants: `EXCURSION_SETTLE_WINDOW_S` (reuses D1's), `EXCURSION_RETURN_BLOCKING = True`, **`EXCURSION_LEASE_SLACK_S`**, **`EXCURSION_LEASE_MAX_S`** | See §6. Lease constants land here in rev-4. |
| Kill switch entity `excursion_primitive_enabled` (begin-only semantics) | See §6 + §4.7. |
| **Tick-side lease check** at the S1 preset-apply path (i.e. inside `_apply_house_state_presets` just before the preset decision at `hvac_preset.py:202-217` is consulted) | The single new consumer of `lease_active(zone_id)`. Replaces reliance on `preset_mode == "manual"` as the hands-off signal for URA-owned zones under active excursion. See §4.4. |

### 2.4 Prior planning docs consulted

- `AUDIT_restart_safety_classification.md` — informs REUSE, PERSIST/RESET/REBUILD declaration.
- `PLANNING_preset_flap_offphase_honesty.md:184-195, :280` — S14 exclusion (§12).
- **HVAC-MANUAL-PRESET-CONTRACT-1** (the sibling card) — §1.2 concurrency analysis + §4.4 lease design derived from it. This cycle and that one MUST ship together or the ordering must have the lease first.
- Kanban card body `HVAC-GOVERNED-EXCURSION-1` at `kanban.data.yaml:2296-2435`.

### 2.5 Design docs read

- No `docs/Coordinator/hvac_override.md` exists (gap flagged, not blocking).

### 2.6 Memory bodies pulled

- `feedback_wire_in_anchor_mandatory.md`, `feedback_suppression_needs_discharge.md`
  (informs lease-expiry design — a lease is a suppression and its expiry IS its
  discharge), `feedback_falsify_before_asserting.md`,
  `feedback_verification_needs_disjoint_framings.md`,
  `feedback_mutation_verification_pycache_staleness.md`,
  `feedback_parent_entry_reload_watchdog_hazard.md`.

---

## 3. Reconciled emission-site enumeration — **15 sites (authoritative)**

Legend: **kind** — one of `nudge / compromise / banking / preheat / egress_pause`.
**role** — `START` (opens excursion), `RETURN` (closes), `GOVERNED_APPLY` (target
state itself; not migrated but MAY consult the lease), `EXCLUDED` (per §9 non-goal).

| # | File:line | Site tag | Kind | Role | Migration action | Neuter-drill enclosing method |
|---|---|---|---|---|---|---|
| 1 | `hvac.py:1981` | S1 | — | GOVERNED_APPLY | **NOT MIGRATED as an excursion. Rev-5 (CORRECTED — rev-4's placement was wrong): this site GAINS a lease check AT THE EMIT MERGE POINT, after the two decision arms converge, immediately guarding `emit_set_preset_mode` at `hvac.py:2013`. NOT before `should_change_preset` — the vacancy arm at `hvac.py:1892-1894` bypasses that consult entirely and would write through a live lease. See §4.4 + AC14b.** If `lease_active(zone_id) == True`, the tick DROPS the preset write for this zone on BOTH arms (matches the comfort-gate DROP policy at `hvac_setpoint.py:12-16`; next tick re-decides — no queueing). If False, the tick proceeds unchanged. This check REPLACES today's implicit `preset_mode == "manual"` lockout as the hands-off signal for zones under active URA excursion. Rev-3's stamp write is DELETED. | `_apply_house_state_presets` |
| 2 | `hvac.py:2274` | S10 | — | GOVERNED_APPLY | **NOT MIGRATED** (DPM apply IS the target state). **The lease check at row 1 applies to the preset path only.** The DPM setpoint path is governed by the arrester's suppression + the S10 comfort gate; a builder MAY add a lease check here for symmetry if framing C or the operator asks, but rev-4 does not require it (the setpoint chokepoint is not the axis snapshot-restore protects). | `_apply_dpm` (name TBV at build) |
| 3 | `hvac.py:2974` | S14 | — | **EXCLUDED** | **NOT MIGRATED** — deliberate indefinite hold per §12; see `PLANNING_preset_flap_offphase_honesty.md:184-195, :280` and shipped test `test_ceiling_held_until_next_preset_transition`. S14 leaves preset alone (`hvac.py:1740-1745`), so §1 invariant is already satisfied at S14. | — |
| 4 | `hvac_override.py:2430` | S3 | `compromise` | START | Replace hand-rolled emit + suppress with `token = await begin_excursion(kind=COMPROMISE, duration_s=self._compromise_minutes*60, ...)`. `_compromise_timers` callback calls `await return_excursion(token, trigger="timer")` in place of `_revert_override`. | `_apply_compromise` |
| 5 | `hvac_override.py:2554` | S4 | `compromise` | RETURN | Body becomes `return_excursion(token, trigger="timer")`. Suppression contract per §4.2. **`original_preset` from the caller is NO LONGER PASSED SEPARATELY** — the primitive uses the snapshot on the row, which was taken at `begin()` and equals what the compromise put on the wire. | `_revert_override` |
| 6 | `hvac_override.py:3122` | S5 | `nudge` | START | Replace lines 3072-3145 with `token = await begin_excursion(kind=NUDGE, duration_s=self._nudge_duration_min*60, ...)`. **The `_nudge_pre_preset` dict is DELETED (§13.5 RULING) — the snapshot inside `begin_excursion` records the pre-write preset UNFILTERED, including `manual`.** `ac_reset_state.in_flight_nudge_*` columns REMAIN authoritative for the nudge daily counter; the primitive dual-writes them from within `begin_excursion(kind=NUDGE)` for backward-compat. `emit_*` calls MUST pass **`blocking=True`**. | `_perform_soft_nudge` |
| 7 | `hvac_override.py:3223` (setpoint) + `:3258` (preset) | (untagged pair) | `nudge` | RETURN (normal) | `_on_nudge_restore_fire` calls `await return_excursion(token, trigger="timer")`. The awaited in-order sequence per §1 replaces the raced non-blocking pair. **Preset write is UNCONDITIONAL when `pre_preset is not None` — the `if _cur_preset == "manual"` gate at `hvac_override.py:3252` is DELETED (§13.5 RULING).** The D1 immediate-read block at `:3281-3329` MOVES INTO the primitive so it runs at step (d). | `_restore_after_nudge` |
| 8 | `hvac_override.py:3891` | S8 | `nudge` | RETURN (cancel) | `cancel_nudge` calls `await return_excursion(token, trigger="cancel", override_target_high=original_target)`. **Preset is now written here too** (was NO today), from the snapshot — same UNFILTERED semantics. | `cancel_nudge` |
| 9 | `hvac_override.py:4170` | S9 | `nudge` | RETURN (startup audit) | `async_startup_ramp_audit` becomes a thin adapter to `async_startup_excursion_audit()` filtered to `NUDGE` for compat. Both guards at `:4096-4145` (Temp-Arrester-Override active; operator re-set during outage) MUST be preserved. **Preset written from the snapshot on the resurrected row** — same UNFILTERED semantics. A lease recovered post-boot is STILL A LEASE (§4.4). | `async_startup_ramp_audit` |
| 10 | `hvac_predict.py:957` | S11 | `banking` | **RETURN** (Reviewer A-HIGH-1) | Wire S11's body as `return_excursion(token, trigger="banking_release")` for `kind=BANKING`. | `_release_banked_zones` |
| 11 | `hvac_predict.py:1047` | S12 | `banking` | START (pre-cool) | `_execute_zone_pre_cool` (`:1006`) calls `begin_excursion(kind=BANKING, duration_s=…)`. Return via S11 (row 10). **The `pre_target_low/high` snapshot MUST come from `_resolve_baseline_range` at `hvac_predict.py:842`**, NOT from live `zone.target_temp_*`, or the ratchet bug at `:858-866` re-strands us. | `_execute_zone_pre_cool` |
| 12 | `hvac_predict.py:1286` | S13 | `preheat` | **START — first-class excursion** (Reviewer A-CRIT-2) | `_execute_pre_heat` (`:1253`) calls `begin_excursion(kind=PREHEAT, duration_s=<seconds until OFF_PEAK_END_HOUR>)`. Add a return callback at `OFF_PEAK_END_HOUR`. **`return_excursion` for `PREHEAT` MUST update `_last_emitted_range[zone_id]` to the restored baseline pair**, or the DPM throttle at `hvac.py:2252-2255` re-strands the +2°F floor. Add rows to `_pre_conditioning_zones.add(zone_id)` in `begin` and remove in `return` for symmetry with pre-cool. See AC10. | `_execute_pre_heat` |
| 13 | `hvac_egress.py:664` | egress_resume (preset) | `egress_pause` | RETURN (preset leg — folded into row 14) | Preset leg of the awaited return sequence. | (folded) |
| 14 | `hvac_egress.py:642` (mode restore) + `:664` (preset) + `:648-651` (currently `return`s on mode-fail, SKIPPING preset — the leak) | egress_resume (mode) | `egress_pause` | RETURN | `_engage_resume` calls `return_excursion(token, trigger="egress_close")`. The primitive performs mode-restore + preset-restore in the awaited order. **Failure contract: if mode-restore raises, still attempt preset-restore, write `restore_ok=False` with `trigger_detail="mode_restore_failed"` — TODAY's early-return at `:648-651` is a silent leak** (Reviewer A-MED-7). See §4.6. | `_engage_resume` |
| 15 | `hvac_egress.py:570-575` (mode-off) + snapshot at `:583-588` + persist at `:592` | (untagged, missing from rev-1 §3) | `egress_pause` | START — **the ONE excursion whose action IS a mode change** | `_engage_pause` calls `begin_excursion(kind=EGRESS_PAUSE, intended_mode=prior_mode, duration_s=None)`. The `pre_preset` on the row is taken from live thermostat state at `begin()` (matches today's snapshot at `hvac_egress.py:583-588`, but WITHOUT the filter — see §13.5). Mode-off MOVES INSIDE `begin_excursion` for THIS kind only — after the DB write, not before (fixes A-HIGH-2 persist-after-actuate defect at `:570-575, :592`). | `_engage_pause` |

**Site totals:** 15 sites total. 10 in-scope for migration; 2 GOVERNED_APPLY (row 1 gains the lease check; row 2 does not); 1 EXCLUDED.

**Raw `set_hvac_mode` count: 7** (`hvac.py:1486`; `hvac_override.py:2537, 2780, 2847, 2882`; `hvac_egress.py:572, 644`). `coordinator.py:1036` is the `_CLIMATE_BLOCKED_SERVICES` guard.

**Bypass audit:** ZERO raw `climate.set_temperature` / `set_preset_mode` calls outside `hvac_setpoint.py` (Reviewer A §1.3).

---

## 4. D2 — the primitive (rev-4: snapshot-restore + lease)

### 4.1 API

```
class ExcursionToken:
    zone_id: str
    excursion_id: str
    kind: EXCURSION_KIND
    started_ts: str          # ISO
    pre_preset: str | None   # SNAPSHOT of preset_mode observed at begin(); may be "manual" or None
    pre_target_low: float | None
    pre_target_high: float | None
    intended_mode: str

async def begin_excursion(
    hass, *,
    zone_id: str,
    entity_id: str,
    kind: EXCURSION_KIND,
    excursion_low: float | None,
    excursion_high: float | None,
    duration_s: int | None,
    freeze_active: bool,
    gate: Callable[[], bool] | None,      # begin path only; passed to emit_*
    site: str,
    reason: str,
    arrester,
    intended_mode: str = "heat_cool",
) -> ExcursionToken | None                 # None ⇒ gate deferred; no row written; no suppress

async def return_excursion(
    token: ExcursionToken, *,
    trigger: Literal["timer","cancel","teardown","startup_audit","exception_recovery",
                     "egress_close","banking_release","preheat_boundary"],
    override_target_high: float | None = None,
) -> ReturnOutcome

async def async_startup_excursion_audit(hass, coord) -> None

def lease_active(zone_id: str) -> bool
    # True iff hvac_excursion_state has an UNEXPIRED row for zone_id.
    # Expiry per §4.4. Cheap (in-memory read against the REBUILD cache
    # of live tokens); no DB hit per tick.
```

**Contract restated (Reviewer B H-3):**
- Every `emit_set_temperature` / `emit_set_preset_mode` call inside `return_excursion` MUST pass `blocking=True`.
- `return_excursion` MUST NEVER pass a `gate=`. Restores are unconditionally ALLOW (deferred-write DROP at `hvac_setpoint.py:12-16` would strand the zone).
- Framing C mutation targets: flip `blocking=True → False` → a named test must fail; add `gate=lambda: True` on a return emit → a named test must fail.

### 4.2 The six things the primitive owns

1. **SNAPSHOT — unopinionated.** DB row written BEFORE the service call (R1 ordering per `hvac_override.py:3055-3062, 3072-3079`). `pre_preset` = raw `hass.states.get(entity).attributes["preset_mode"]` observed at `begin()` (may be `"manual"`, may be `""`, may be missing — see §4.3). `pre_target_low/high` = raw observed setpoints (with the banking exception at row 11 that reads `_resolve_baseline_range` to sidestep the ratchet).
2. **SUPPRESS — direction depends on path:**
   - Begin path: `arrester.suppress(entity, kind=…)` AFTER `emit_*` returns True; on defer roll back via `arrester.unsuppress(entity)` (A-MED-2 discipline at `hvac.py:2258, 2286-2294`).
   - Return path: `arrester.suppress(entity, kind=…)` BEFORE the `emit_*` write — DELIBERATELY OPPOSITE rule (`hvac_override.py:3215-3217, 3218, 3254`). A builder inverting this by uniform-application starts mis-classifying URA's own restore as a user override (Reviewer B M-3).
3. **CHOKEPOINTS UNCHANGED** — every wire write via `emit_*`. Freeze floor + deadband + comfort gate inherited unchanged.
4. **AWAITED RETURN, DETERMINISTIC ORDER** — (a)(b)(c)(d) per §1. Immediate read is step (d), post-(c).
5. **RECORD** — populate `ac_ramp_events` for NUDGE via the new nullable `excursion_id` column; `hvac_excursion_events` for the other four kinds.
6. **RESTART BACKSTOP** — `async_startup_excursion_audit()` generalises `async_startup_ramp_audit` (`hvac_override.py:4057`), preserving BOTH guards at `:4096-4145`. Do NOT rewrite the audit; generalise it.

### 4.3 Snapshot-restore — the RULING (§13.5 CLOSED)

**Design:** the excursion snapshots exactly what it finds at `begin()` and restores
exactly that at `return()`. No filter. No intent resolution. No decision about
whether the snapshot "deserves" to survive.

Concretely, at `begin_excursion`:
```
st = hass.states.get(entity_id)
pre_preset  = st.attributes.get("preset_mode")           # may be "manual", "", or None
pre_low     = st.attributes.get("target_temp_low")       # or _resolve_baseline_range for BANKING
pre_high    = st.attributes.get("target_temp_high")
```
No `if pre_preset != "manual"` filter. No `if pre_preset` truthy check. Whatever
was on the wire is what the row records; whatever the row records is what
`return_excursion` writes back (with `pre_preset is None` as the ONLY skip — no
value to write).

**Why this is right (operator ruling, verbatim):** *"restore paths should take
snapshots of the starts and also understand the intention so they can restore to
those… Basically be unopinionated and let other mechanisms that are appropriate
decide. Unless an opinion is part of the goal."* On the midnight-manual case:
*"A midnight thermo yank is not guarded afaik. It's fair game for an arrester. At
least at this point. Easiest way is to change the preset itself which is what dpm
and preset management is for."*

**What this dissolves:**
- **Self-disarm latch** — `pre_preset='manual'` yields `restore_preset='manual'`;
  equality holds; `restore_ok=1`. No conditional to get stuck in. Rev-3's stamp
  apparatus existed ONLY to answer "what SHOULD be there now?" — a question the
  excursion no longer asks. All of it is deleted (see below).
- **The "URA fights the operator" hazard** — the excursion cannot induce a preset
  it did not find. If an operator sets `manual` mid-nudge and the excursion put
  `manual` there, the restore replaces `manual` with `manual` — a no-op from the
  operator's perspective.

**What this DOES NOT dissolve, and why that is not this cycle's problem:** if the
thermostat was already stuck in `manual` before the nudge (14-hour-block situation)
the excursion restores `manual` — same state as before, no worse. The stuck
`manual` is a symptom of the accidental lockout (§1.2) and is fixed by
HVAC-MANUAL-PRESET-CONTRACT-1 unblocking ticks during `manual` so the reason
ladder can WRITE the intended preset. That is another card's mechanism; the
excursion's job is only to not make it worse.

**Stamp apparatus removed:** rev-3's `ZoneState.last_intended_preset`, the S1
producer-contract stamp write, the `resolve_intended_preset` function signature,
AC13, and every other reference are DELETED. The excursion's `pre_preset` field
replaces them. This is a SIMPLIFICATION — the excursion carries less state, has
less policy, and is easier to reason about than either the extract-into-resolver
option or the stamp option. The self-disarm defect is fixed with fewer moving
parts than rev-2 or rev-3 proposed.

### 4.4 The lease — explicit ownership with visible, bounded expiry

**Design:** an active `hvac_excursion_state` row IS the lease. No new machinery.
`lease_active(zone_id)` reads an in-memory `REBUILD` cache of live tokens (populated
by `begin_excursion` and by `async_startup_excursion_audit`; cleared by
`return_excursion` and by expiry). Cost: one dict lookup per tick per zone.

**Where the tick checks it — THE MERGE POINT, NOT THE CONSULT (rev-5 correction).**
The check goes inside `_apply_house_state_presets` **after the branch converges and
immediately before the emit** (`hvac.py` ~:1970-2013, guarding the
`emit_set_preset_mode` call at :2013). It MUST NOT go before `should_change_preset`
(`hvac_preset.py:202-217`).

**Why — this is load-bearing, do not "simplify" it back:** the preset decision has
TWO arms. The vacancy arm at `hvac.py:1892-1894` explicitly bypasses the consult
(`# Bypass should_change_preset() manual guard for vacancy (RH3 fix)`), so a check
placed before the consult is unreachable on that path — a vacancy sweep would write
`away` through a live excursion and the lease would report clean. Both arms converge
on one emit. **Gating the write is structural: it cannot be bypassed by a future
branch, which is precisely how the existing bypass got in.** Gating the consult is
positional and silently breaks the next time someone adds an arm.

If `lease_active(zone_id) == True`:
- The tick DROPS the preset decision for this zone for THIS tick — matches the
  comfort-gate DROP policy at `hvac_setpoint.py:12-16`. The comfort gate exists
  precisely to model "granted then snatched" as an antipattern; the lease follows
  the same rule.
- The tick DOES NOT queue the decision. The reason ladder recomputes each tick
  anyway, so a real change will re-emit naturally when the lease clears (worst
  case one tick, per staleness bound below).
- The tick emits an activity-log row (level=debug) so the deferral is visible in
  the ledger.

**This check REPLACES today's implicit `preset_mode == "manual"` lockout as the
hands-off signal for URA-owned zones.** Today, ticks defer because `should_change_preset`
returns False when the thermostat reports `manual` — a preset URA induced as a
side effect. The lease says explicitly "URA owns this zone right now." Operator-set
manual (a real thermo yank) is NOT protected by the lease — it never was, and per
the operator's ruling that is the arrester's job, not the excursion's.

**Expiry — three-line rule:**

For a lease with `duration_s` (nudge, compromise, preheat with computed hour boundary):
```
expiry_ts = min(started_ts + duration_s + EXCURSION_LEASE_SLACK_S,
                started_ts + EXCURSION_LEASE_MAX_S)
```
For an unbounded lease (`duration_s is None`; egress, some banking):
```
expiry_ts = started_ts + EXCURSION_LEASE_MAX_S
```
See §6 for values (`EXCURSION_LEASE_SLACK_S = 30`, `EXCURSION_LEASE_MAX_S = 7200`).

**Stuck-lease visibility (falsification obligation #8):** the primitive runs a
lightweight housekeeping pass on the same 5-min HVAC decision cycle that already
consults it. When a tick observes an expired-but-still-present lease row, it:
1. Treats the lease as absent (`lease_active` returns False; tick proceeds normally).
2. Fires a `stuck_excursion_lease` NM alert (severity=high) with the zone, kind,
   started_ts, and elapsed time — uses the existing `_stuck_signal_nm.fire_stuck_signal`
   pattern already imported at `hvac.py:1624`.
3. Clears the `hvac_excursion_state` row with `trigger="lease_expired"`,
   `restore_ok=NULL, trigger_detail="lease_expired_no_return"`. The physical
   thermostat is NOT touched — a return that never fired left the wire in an
   unknown state and the primitive is not entitled to guess.

The stuck-lease NM emit is the single "visible, time-bounded" property Reviewer B
H-8 would ask for: an accidental lockout is invisible and permanent; the lease is
visible, expiring, AND alerts on expiry. That is the qualitative difference §1.2
asserts is the point of this exercise.

**Restart interaction:** `async_startup_excursion_audit()` populates the in-memory
lease cache from the persisted rows it recovers. **A lease recovered post-boot is
still a lease** — same `started_ts`, same expiry rule. A row that has already
exceeded `EXCURSION_LEASE_MAX_S` at boot is treated as expired by the audit itself
and cleared with the stuck-lease NM emit (this is the boot-safety guard on a
maximally-stale lease).

**Staleness bound — worst case is ONE tick:**

Given the current constants: 5-min HVAC decision cycle
(`HVAC_DECISION_INTERVAL_SECONDS` — TBV in code); 120-s soft-nudge hold; ~72-s AC
ramp-down median. Straddle probability ≈ `nudge_duration / tick_interval` ≈
`120 / 300` ≈ **40%** of nudges straddle a tick. When one does, the tick during
the lease DEFERS; the next tick re-decides using the current governed state. So
worst-case preset staleness under snapshot-restore + lease is one tick (~5 min)
of the pre-nudge preset persisting after a house-state change.

**Compare to status quo:** today, the `preset_mode == "manual"` lockout (§1.2) can
persist for HOURS — the observed 14-hour zone-1 block is the reference case. The
lease trade is "≤5 min worst-case staleness after a mid-excursion transition, in
~40% of nudges" vs. "unbounded staleness whenever a manual-induction latches" —
a strict improvement in every dimension the operator cares about.

**NOT a lever for this problem — say so:** shortening the HVAC decision cycle from
300 s → 60 s only moves straddle probability from ~40% → ~20% (linear improvement),
at the cost of truncating a meaningful share of nudges before the compressor
responds to them (72-s median ramp-down; a 60-s cycle window is a real functional
regression on the AC-ramp mechanism this cycle is trying to preserve). Cycle
length stays where it is; the lease is the correct mitigation.

### 4.5 State declaration + tables (rev-4: unchanged from rev-3)

Per RESTART-SAFETY-DOCTRINE-1: `hvac_excursion_state` is **PERSIST**, hazard class
(b) PENDING RETURN + (c) LIVE SUPPRESSION/LOCK (the lease IS a live suppression,
and the row's expiry is its discharge — `feedback_suppression_needs_discharge.md`
satisfied by construction). `_excursion_tokens: dict` is **REBUILD** (rehydrated
from persisted rows by the boot audit). **Rev-3's `ZoneState.last_intended_preset`
is DELETED — no such field exists in rev-4.**

**`hvac_excursion_state`** (PK `zone_id`):

```
zone_id                 TEXT PRIMARY KEY
excursion_id            TEXT NOT NULL
kind                    TEXT NOT NULL
started_ts              TEXT NOT NULL
duration_s              INTEGER               -- NULL = caller-owned lifetime
pre_preset              TEXT                  -- raw snapshot, may be "manual"; NULL = no preset attr at begin
pre_target_low          REAL
pre_target_high         REAL
excursion_target_low    REAL
excursion_target_high   REAL
intended_mode           TEXT NOT NULL
caller_site             TEXT NOT NULL
```

**`hvac_excursion_events`** — non-nudge kinds only. Columns mirror the D1 shape on
`ac_ramp_events` plus `excursion_id`, `kind`, `trigger`, `trigger_detail`, `site`,
`duration_actual_s`.

**`ac_ramp_events`** gains a new nullable `excursion_id TEXT` column. Nudge writes
only here — no dual-write.

**Authority rule per kind** (Reviewer A-HIGH-3):

| Kind | Authoritative row | Notes |
|---|---|---|
| `nudge` | `ac_ramp_events` (with new `excursion_id`) | Preserves D1 sensors and AC8 rate comparison |
| `compromise` | `hvac_excursion_events` | |
| `banking` | `hvac_excursion_events` | Interacts with `_first_eval_done` reconciler — see below |
| `preheat` | `hvac_excursion_events` | S13 — see AC10 |
| `egress_pause` | `hvac_excursion_events` (primary) + existing `_db_save_paused_full` at `hvac_egress.py:592` (kept for compat; the primitive row is authoritative for RETURN correctness; the egress table remains authoritative for the "which room triggered" metadata that only egress cares about) | Reviewer A-HIGH-3 (1) |

**`_first_eval_done` (`hvac_predict.py:508-536`) — collision avoidance:**
`async_startup_excursion_audit()` is filtered to `kind IN (NUDGE, COMPROMISE, PREHEAT, EGRESS_PAUSE)` — deliberately excludes `BANKING`, letting the existing `_first_eval_done` scan continue to own boot-reconciliation for banking. Banking `hvac_excursion_state` rows are cleared on boot as housekeeping but not acted on.

### 4.6 Return-sequence failure contract (unchanged from rev-3)

Per-step outcome table. `return_excursion` MUST follow this; the state row is cleared per the "clear?" column.

| Step | Fails | Do next | `restore_ok` | Clear row? |
|---|---|---|---|---|
| (a) `set_temperature` raises | Log error; still attempt (b) (preserves `hvac_override.py:3229-3234`) | Continue | 0 | Yes |
| (b) `set_preset_mode` raises | Log error; still attempt (c) | Continue | 0 | Yes |
| (c) `set_hvac_mode` re-assert raises | Log error | Skip (d); return | 0 | Yes (egress: `trigger_detail="mode_restore_failed"`) |
| (d) immediate read raises | Skip immediate; settled callback still fires | None-immediate | Not yet — settled clears | (settled) |
| Settled callback fires | Reads state → computes `restore_ok` → writes row → clears state row | 0 or 1 | Yes |
| `return_excursion` called twice on same token | Second is a no-op; cached `ReturnOutcome` | (cached) | Already cleared |
| `begin_excursion` for a zone with an existing state row | **REJECT** — return `None`, log warning, do NOT overwrite | — | — |
| Coordinator teardown (unload) | Row stays persisted; boot audit picks it up. No wire calls during unload | — | No — deliberate |
| **Lease expiry with no return** (stuck lease) | Housekeeping tick emits `stuck_excursion_lease` NM alert; clears row with `trigger="lease_expired"`; wire untouched | NULL | Yes |

### 4.7 Kill-switch semantics (unchanged from rev-3)

`excursion_primitive_enabled` is a Switch, RestoreEntity, following
`switch.py:5993-6083` + `hvac.py:317-319` seed + `hvac.py:617-625` property pair.

**Semantics: BEGIN-ONLY.**

- Switch OFF ⇒ `begin_excursion` returns `None` immediately (no state row, no lease, no suppress, no wire write).
- Every already-persisted `hvac_excursion_state` row STILL FIRES `return_excursion` at timer callback and at boot audit.
- Boot ordering: Switch restores in `async_added_to_hass` (platform setup, AFTER coordinator setup); the audit only returns already-persisted rows (safe regardless of switch); the constructor kwarg seed at `hvac.py:317-319` covers the first-tick window.
- The `_legacy_*` dual-path fallback proposed in rev-1 is DELETED (doubles mutation-drill surface for a rollback story the persisted-row semantics make unnecessary).
- **The lease check at row 1 (§3) is INDEPENDENT of the kill switch** — a lease that already exists deserves to be honoured whether the switch is ON or OFF (otherwise flipping the switch OFF creates a lease-vs-tick race exactly when we said we were trying to make things safer).

---

## 5. UNVERIFIED items remaining

- **U3 (LOW):** `async_startup_ramp_audit` at `hvac_override.py:4057` — cite the SYMBOL, not the line, so drift stops mattering.
- **U4 (LOW):** enclosing-method names for `_apply_dpm` and preheat — framing C resolves at build time.
- **U5 (LOW, new in rev-4):** `HVAC_DECISION_INTERVAL_SECONDS` — the 300 s value used in the §4.4 staleness math is a common value across the module docstrings but I did not personally re-open the constant definition. If it is a different value (e.g. 60 s already), the ~40% straddle math changes proportionally and §4.4 must be re-stated. Framing C or the build agent confirms; the design does not depend on the exact number, only on "worst case is one tick."

---

## 6. Knob ladder (rev-4: two lease constants added)

| Constant / entity | Value | Rung | Why |
|---|---|---|---|
| `EXCURSION_SETTLE_WINDOW_S` | reuse `AC_NUDGE_RESTORE_SETTLE_DELAY_S = 12` | 1 (module const) | Cloud-poll cadence interaction. |
| `EXCURSION_RETURN_BLOCKING` | `True` | 1 | The `blocking=True` contract on return-path emits; named so mutation drill can flip at one point. |
| `EXCURSION_KIND` | `StrEnum` × 5 | 1 | Fixed set. `HARD_RESET_PRESET_ASSERT` deliberately absent. |
| **`EXCURSION_LEASE_SLACK_S`** | **`30`** | **1 (module const)** | **Grace beyond a bounded `duration_s` before the lease is treated as expired by ticks. Covers the settle window + a small margin for cloud-poll latency. Safety knob — a live-tuning knob here would let an operator create the accidental-permanent-lock scenario the lease exists to prevent.** |
| **`EXCURSION_LEASE_MAX_S`** | **`7200` (2 hours)** | **1 (module const)** | **Absolute cap on lease age regardless of `duration_s`. Sized to comfortably cover a legitimately long egress (front door held open through a party) while still being an order of magnitude below the 14-hour stuck-manual observations that motivated the cycle. Any lease older than this is stuck, per §4.4 + falsification obligation #8. Safety knob at rung 1 for the same reason as SLACK — an operator-tunable cap invites the exact failure mode being fixed.** |
| `excursion_primitive_enabled` | default `True`; RestoreEntity | 3 (Switch entity) | Kill switch, begin-only semantics per §4.7. Pattern: `switch.py:5993-6083` + `hvac.py:317-319` + `hvac.py:617-625`. |

**Deliberately NOT added (Reviewer B H-4):** `EXCURSION_RETURN_MAX_RETRIES` and `EXCURSION_RETURN_RETRY_DELAY_S`. The `_verify_restore` retry ladder does not transfer cleanly to the preset axis. The D1 settle callback ALREADY measures the failure.

**Deliberately NOT a knob (operator direction):** the HVAC decision cycle length as a lever for straddle staleness. See §4.4 — tuning it costs real function on the AC-ramp mechanism this cycle is preserving.

---

## 7. Acceptance criteria (rev-4: AC13 deleted; AC14 + AC15 added for lease)

Every AC states what the observation looks like under the fix AND under a plausible
different failure. Discriminators drawn from §1.1.

### AC1 — invariant (rewrites the false-PASS from BP-2) — unchanged from rev-3

**Pass predicate:**
```sql
SELECT COUNT(*) FROM ac_ramp_events
WHERE event_type='nudge_restored'
  AND excursion_id IN (SELECT excursion_id FROM ac_ramp_events
                       WHERE event_type='nudge_started'
                         AND preset_before IS NOT NULL
                         AND preset_before <> 'manual'
                         AND ts >= <deploy_ts>)
  AND (restore_ok = 0 OR restore_ok IS NULL)
  AND ts >= <deploy_ts>;
```
**Diagnostic split:** `immediate=1,settled=0` = late clobber; `immediate=0,settled=0` = write never landed / arrived after read. Both go to zero post-fix.

### AC2 — teardown semantics — unchanged from rev-3

*"After a config-entry reload, every `hvac_excursion_state` row present at unload
is either returned or dropped-by-guard within `EXCURSION_SETTLE_WINDOW_S` of
reload complete."* Discriminator: rows persisting past the window = boot audit
didn't fire.

### AC3 — self-disarm — REPHRASED for rev-4

*"After a zone spends >1 h in `preset_mode='manual'` and a nudge fires, JOIN
`nudge_started` and `nudge_restored` on `excursion_id`; started row has
`preset_before='manual'`; restored row has `preset_after='manual'` AND
`restore_ok=1`."* Under rev-4 snapshot-restore, restoring `manual` to a
`manual`-snapshotted excursion is EQUALITY — the settled callback records
`restore_ok=1`. The old defect (self-disarm) presented as either no
`nudge_restored` row OR `preset_after != preset_before` with `restore_ok=NULL`.
Distinguishable.

### AC4 — restart safety — unchanged from rev-3

Restart HA while a nudge is in-flight. After boot, `hvac_excursion_state` has 0
rows for that zone AND `preset_mode == pre_preset` within
`EXCURSION_SETTLE_WINDOW_S + duration_remaining_s`.

### AC5 — test authority (framing C) — rev-3 wording revoked for the stamp mutation drill

Per-site mutation drill for every row in §3 with a defined enclosing method. **The
rev-3 stamp-write mutation on row 1 is DELETED** (the stamp write no longer
exists). **Row 1 keeps a NEW mutation drill: delete the lease check —
AC14 fails.** Row 2 (`_apply_dpm`) and row 12 name-verification unchanged.

### AC6 — falsifiability (framing D) — unchanged

D produces zero unresolved leaks against §1 invariant.

### AC7 — kill switch — unchanged from rev-3

With switch OFF, `begin_excursion` returns `None` at every migrated site (mutation-anchored). Already-persisted rows still fire `return_excursion`.

### AC8 — Tier 2-DB row-shape compat — unchanged

`ac_ramp_events` D1 columns populated for the nudge; 24 h non-NULL rate within ±25% of pre-deploy snapshot. Degradation clause if <24 h D1 data.

### AC9 — mutation-anchored regression check — unchanged

For every §3 START/RETURN row, per-site mutation test proves the site emits through the primitive. Chained-route bypass explicitly out of scope.

### AC10 — S13 pre-heat return + `_last_emitted_range` update — unchanged from rev-3

### AC11 — Egress persist-before-actuate — unchanged from rev-3

### AC12 — Egress mode-fail → preset-still-attempted — unchanged from rev-3

### ~~AC13 — Stamp equivalence with S1 emit~~ — **DELETED** in rev-4

Rev-3's AC13 anchored the stamp mutation drill. Snapshot-restore has no stamp.

### AC14 — Lease honoured by the tick (NEW — rev-4)

*"With an active lease on zone Z (an `hvac_excursion_state` row exists and is
unexpired per §4.4), a decision tick invoked on Z DOES NOT WRITE the wire on the
preset axis. Proven by test: seed a lease row, invoke `_apply_house_state_presets`,
observe zero `climate.set_preset_mode` service calls dispatched for Z. Mutation:
delete the `lease_active(zone_id)` check at the emit merge point (row 1 of §3) — the
test must fail."*

**AC14b — the vacancy arm is gated too (NEW, rev-5, MANDATORY — not optional):**

*"With an active lease on zone Z, a tick in which Z is ALSO vacant past grace (or
`runtime_exceeded`) with `effective_preset == 'away'` — i.e. the arm that BYPASSES
`should_change_preset` at `hvac.py:1892-1894` — STILL writes nothing on the preset
axis. Proven by a test that drives that specific branch, not the general path."*

**This test is the adherence guarantee for the rev-5 placement.** It fails if a
builder puts the lease check back before the consult, because the vacancy arm never
reaches the consult. A lease check that passes AC14 but fails AC14b is in the wrong
place, and no amount of AC14 greenness redeems it. **Reviewer C must verify AC14b by
real source mutation on the vacancy arm specifically** — an aggregate lease
monkeypatch proves nothing about which arm routes through the gate.

**Discriminator:** under the fix, the tick reads the lease and drops the decision.
Under a lease-miss defect, the tick writes and the settled callback records a
divergence (`preset_after != pre_preset`, `restore_ok=0` on the eventual return).
Two distinguishable failure paths.

### AC15 — Lease expiry visible and bounded (NEW — rev-4, satisfies falsification #8)

*"A `hvac_excursion_state` row whose row age exceeds
`min(started_ts + duration_s + EXCURSION_LEASE_SLACK_S, started_ts + EXCURSION_LEASE_MAX_S)`
(or `started_ts + EXCURSION_LEASE_MAX_S` when `duration_s IS NULL`) fires exactly
one `stuck_excursion_lease` NM alert AND is cleared with `trigger='lease_expired',
restore_ok=NULL, trigger_detail='lease_expired_no_return'` within one HVAC decision
cycle. The physical thermostat state is NOT changed by the housekeeping — the wire
is left in whatever state the un-returned excursion left it."*

**Discriminator:** under the fix, an accidentally-stuck lease surfaces as an NM
alert AND self-clears within ≤1 cycle. Under a broken housekeeping path, the row
stays persisted indefinitely and ticks defer forever (the exact accidental-lock
failure mode the lease exists to prevent, now in explicit form). The NM alert
absence + row persistence is the discriminating signature.

### Live validation (Review D — post-restart)

README carries a `Validated <date>` table with one row per AC1, AC4, AC10, AC11,
AC12, **AC14, AC15**, each citing entity_id / DB read / log line.

---

## 8. Non-goals (rev-4: non-goal 12 restated; new non-goal 13)

1. Freeze floor and deadband stay in `hvac_setpoint.py`.
2. Mode-axis migration is OUT for 6 of 7 excursion kinds — the seven raw `set_hvac_mode` sites are NOT migrated. Egress (row 15) is the sole exception.
3. AC-ramp recurrence trigger + partitioned reset budgets — separate card.
4. No cost accounting changes.
5. No comfort-delay semantics changes.
6. `hard_reset_preset_assert` is NOT a primitive-managed kind. Instead, add a
   one-line `emit_set_preset_mode(...)` at `hvac_override.py:2913-2917` in the
   `_verify_restore` success branch. **Rev-4: the preset value to write comes from
   snapshotting `hass.states.get(entity).attributes["preset_mode"]` at the top of
   `_perform_ac_reset` (before the off-write) and storing it on `ac_reset_state`
   OR passing it through as a local variable — this is a small, self-contained
   snapshot pair on the hard-reset lifecycle, NOT a routing through the excursion
   primitive.** Marginal-benefit + lifecycle-collision arguments still hold.
   `EXCURSION_KIND` StrEnum MUST NOT contain a member for this.
7. Do NOT rewrite `async_startup_ramp_audit`. Generalise, do not replace.
8. Do NOT delete `ac_reset_state.in_flight_nudge_*` columns.
9. Do NOT dual-write nudge outcomes. Nudge writes ONLY to `ac_ramp_events`.
10. Do NOT migrate S14 — see §12.
11. Do NOT invert the return-path suppress order.
12. **Do NOT extract the `effective_preset` ladder into a resolver. The excursion
    does not resolve intent at all** (§4.3 snapshot-restore) — extraction was
    proposed in rev-3 to power a stamp; snapshot-restore removes the need for
    both. The rev-3 verification of side effects at `hvac.py:1534-1749`
    (`_execute_vacancy_sweep` at `:1558, :1610`, sweep-done + counter mutations,
    `continuous_occupied_since` at `:1593`, `_d3_skipped_current_tick` at `:1749`,
    AND `_apply_duty_off_phase` at `:1730`) also independently forbids the
    refactor. Non-goal stands with the stronger reason.
13. **Do NOT shorten the HVAC decision cycle as a straddle-staleness mitigation.**
    The lease is the correct mitigation; cycle length stays where it is for
    feedback / sample-rate reasons (§4.4 explanation).

---

## 9. Migration safety — Tier 2-DB triggers

- **New DAO / new persisted table** — write volume estimate: nudge ~430 rows/day
  to `ac_ramp_events` (unchanged); non-nudge ~200 rows/day to
  `hvac_excursion_events`. **Lease housekeeping adds zero DB writes on the happy
  path** (in-memory cache read; row cleared by the normal return). A stuck-lease
  clear is ~1 write per stuck lease per cycle, and stuck leases should be rare
  (that is the point of AC15). Direct dispatch safe; three orders of magnitude
  below the write-flood threshold.
- Migrates ≥3 callers to new DAO — YES (10 in-scope, 5 kinds).
- Changes payload shape — `ac_ramp_events` gains one nullable column. D1 columns preserved.
- Behavioural test infra against real schemas.
- Pre-deploy snapshot per Tier 2-DB standard.

---

## 10. Concerns with the brief — RESOLVED across revs

Rev-1 §11 offered options; Reviewers A + B + operator converged:

1. **`hard_reset_preset_assert`** — DROP (per §9.6). Small self-contained snapshot pair on the hard-reset lifecycle, not routed through the primitive.
2. **Dual-write vs `excursion_id` column** — SINGLE-TABLE with nullable `excursion_id` on `ac_ramp_events`.
3. **Rev-3 stamp vs. rev-2 extraction** — BOTH SUPERSEDED. Rev-4 snapshot-restore does not resolve intent; both options addressed a question the excursion no longer asks. See §4.3.
4. **`_nudge_pre_preset` filter** — operator ruled: DELETED. Snapshot is UNFILTERED. Rows 6, 7, 15 in §3 reflect this. See §13.5 (now CLOSED).

---

## 11. Findings I did NOT accept, with reasons

Every CRITICAL and HIGH from both reviews is folded in. Where I diverged:

- **Reviewer A-LOW-2 (banking ratchet):** partial. The banking snapshot in `begin_excursion` reads `_resolve_baseline_range` (`hvac_predict.py:842`) to be ratchet-immune. **I did NOT scope fixing the ratchet at `:858-866` itself** — separate defect in `_execute_zone_pre_cool`'s own logic. Backlog note stays open.
- **Reviewer B L-3 (deferred-write ledger site-tag allowlist at `hvac_setpoint.py:90-92`):** accepted; every new site tag added to the allowlist during D3. Called out for Reviewer C's mutation drills.
- **Reviewer A-MED-3 citation drift:** accepted; `comfort_delay_active` cited at `:1498` since rev 2. Other spot-checked citations trusted from A's independent read.
- **Reviewer B BP-1 option (a) — extract into a resolver — and option (b) — stamp at emit time:** BOTH SUPERSEDED in rev-4. Rev-3 chose (b); rev-4's snapshot-restore makes the question moot. Recorded here so a future reviewer does not re-open it. See §4.3.
- **§13.5 Branch A / Branch B:** neither accepted — operator ruled for a third design (§13.5 body below now describes the ruling, not the branches).
- **Interaction with HVAC-MANUAL-PRESET-CONTRACT-1:** the lease (§4.4) is NEW scope in rev-4 driven by that card's imminent removal of the accidental `manual`-based lockout (§1.2). If HVAC-MANUAL-PRESET-CONTRACT-1 slips such that this cycle ships FIRST, the lease is still correct (it replaces the accidental lockout with an explicit one immediately; no harm). If this cycle slips such that HVAC-MANUAL-PRESET-CONTRACT-1 ships first, snapshot-restore is unsafe without the lease and this cycle MUST include the lease before its migration lands. Either way, this cycle carries the lease.

---

## 12. Parked-plan trigger — HVAC-PRESET-FLAP-1 FIRES on S14

**Parked plan:** `docs/planning/PLANNING_preset_flap_offphase_honesty.md`
**Firing trigger:** rev-1 proposed migrating S14. Both branches (no-op wrap / long-lived excursion with return) undo the documented deliberate trade:

- `:184-195`: *"by design, once the S14 helper writes the `home + OFFSET` ceiling and later `runtime_exceeded` clears, URA … the ceiling holds at `home + OFFSET` until the next preset transition."*
- `:280` states a Live acceptance criterion asserting NO follow-on restore write fires.
- Shipped test `test_ceiling_held_until_next_preset_transition` enforces this.
- S14 already leaves preset alone (`hvac.py:1740-1745`), so §1 invariant is ALREADY satisfied at S14.

**Resolution:** S14 EXCLUDED from D3 (row 3 in §3). §9 non-goal 10 records it. Rev-3's extraction-would-have-re-opened note stands; rev-4 additionally records that snapshot-restore alone (without the extraction) would also have re-opened this exclusion if S14 had been included as a migrated kind, because snapshotting S14's ceiling and later "restoring" the pre-ceiling state IS the release-write the parked plan forbids.

If the operator wants the ceiling to self-release, that is a separate card that re-litigates PRESET-FLAP-1.

---

## 13. Open decisions

### 13.1 — 13.4: RESOLVED across revs (see §10)

### 13.5 — **CLOSED (rev-4) by operator ruling: UNOPINIONATED SNAPSHOT-RESTORE**

Rev-2 through rev-3 posed this as Branch A (delete filter + unconditional
manager-sourced restore + new immune-hold exception) vs Branch B (keep filter,
move into primitive). The operator ruled for a **third design** that neither
branch anticipated:

**Restore paths snapshot exactly what they find at `begin()` and restore exactly
that at `return()`. No filter. No intent resolution. No decision about whether
the snapshot deserves to survive.**

Operator, verbatim: *"restore paths should take snapshots of the starts and also
understand the intention so they can restore to those… Basically be unopinionated
and let other mechanisms that are appropriate decide. Unless an opinion is part
of the goal."* And on the midnight-manual case: *"A midnight thermo yank is not
guarded afaik. It's fair game for an arrester. At least at this point. Easiest
way is to change the preset itself which is what dpm and preset management is
for."*

**Consequences folded into rev-4:**
- `_nudge_pre_preset` is DELETED (§3 rows 6, 7).
- The `if _cur_preset == "manual"` gate at `hvac_override.py:3252` is DELETED (§3 row 7).
- Rev-3's `ZoneState.last_intended_preset` stamp field, the S1 producer-contract stamp write, the `resolve_intended_preset` function, and AC13 are all DELETED (§4.3 + §7).
- Non-goal 12 restated: the excursion does not resolve intent at all.
- The mid-excursion clobber that snapshot-restore now exposes (once
  HVAC-MANUAL-PRESET-CONTRACT-1 unblocks manual-based ticks) is prevented by the
  EXPLICIT LEASE, §4.4.

**Not the operator's decision to make and not asked:** the small hard-reset
preset-assert (§8 non-goal 6) — kept as a self-contained snapshot pair on the
hard-reset lifecycle, described in the non-goal body.

---

*End of REV-4 plan. §13.5 CLOSED by operator ruling. Rev-4 removes the stamp
apparatus in favour of unopinionated snapshot-restore + explicit lease.
Framing-disjoint Tier-3 plan reviews A + B are in from rev-2; rev-3 addressed the
resolver-vs-stamp distinction; rev-4 supersedes both with the operator's
snapshot-plus-lease design. Ready for build dispatch.*
