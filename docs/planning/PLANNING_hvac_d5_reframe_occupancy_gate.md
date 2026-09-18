# PLANNING — HVAC-D5-REFRAME-AND-OCCUPANCY-GATE-1

**Date:** 2026-09-17
**Card:** `HVAC-D5-REFRAME-AND-OCCUPANCY-GATE-1` (`docs/planning/kanban.data.yaml:472`)
**Absorbs (proposed):** `HVAC-D5-KNOBS-TO-RUNG-3-1` (`kanban.data.yaml:495`) — folded per its own
`next:` ("fold into HVAC-D5-REFRAME-AND-OCCUPANCY-GATE-1 if built together").
**Audit basis:** `docs/planning/AUDIT_hvac_duty_cycle_protection_2026_09_17.md`
**Tier:** **Tier 2-DB (regression-prone)** — reasons in §Tier Classification.
**Status pre-build:** requires OPERATOR CHECKPOINT before build dispatch (see §Operator Checkpoint).

---

## 0. Tier Classification

Tier 2-DB per CLAUDE.md standing policy ("default to elevating for regression-prone work"):

- **Trust-hierarchy ripple.** Change touches the presence ↔ HVAC ↔ energy (EC coast/shed)
  axis. D5 lives on the shared away-writer path (`hvac.py:2081`) that D1 vacancy, D3
  comfort-delay, D4 stale-occupancy, D6 stuck-signal, and pre-arrival all traverse. A wrong
  precedence change here can silently break coast energy savings or reintroduce hot-occupied-
  away.
- **Shared-primitive consumer swap.** Adds a *new consumer* of `zone.any_room_hvac_occupied`
  (shipped v5.103.7, live at `hvac.py:1893`) — a fused-occupancy signal already load-bearing
  for D1/D4/D6/D7. A miscoded gate can invert its meaning at exactly one site.
- **Reason-ledger surface.** `runtime_exceeded` is a member of `HVAC_PRESET_REASONS`
  (`const.py:1266`) and is asserted by the reason-precedence test
  `TestReasonLadderPrecedence` (referenced at `hvac.py:2286`). Any rename or new label must
  preserve ledger allow-list membership + precedence order + backward-compat readers.

Three framing-disjoint reviews mandatory:
- **A — Local correctness.** Occupancy gate arithmetic, precedence, `sleep`/`comfort_delay`
  interaction, kill-switch semantics, reason-ledger allow-list.
- **B — Integration / state-machine integrity.** No regression to coast energy savings on
  UNoccupied zones; SHED unchanged on OCCUPIED zones; D1/D4/D6/D3 unaffected; restart /
  reload behavior; `_row4_fused` fallback (`hvac.py:1894-1895`) when
  `any_room_hvac_occupied` is None.
- **C — Test authority + adversarial completeness.** Per-site source mutation on the new
  occupancy gate (neuter the check, assert the discriminating test fails); enumerate every
  emission site that reads `runtime_exceeded` (already 12 hits in `hvac.py` grep — §5.1) and
  confirm each one's behavior under the new gate.

---

## 1. Institutional context verified

### Greps run + results

| Proposed piece | Verdict | Existing at |
|---|---|---|
| Fused occupancy input `zone.any_room_hvac_occupied` | **REUSED** | `hvac.py:1893` (D6 stuck-sensor gate), `hvac.py:1825`/`:1837` comments — the same fused HVAC-scoped signal step-4-B put in place |
| Coast/shed accessors `energy_constraint_mode`, `shed_active` | **REUSED** | `hvac.py:678`, `hvac.py:747-751` |
| Reason-ledger allow-list `HVAC_PRESET_REASONS` | **REUSED (extend)** | `const.py:1262-1266` (contains `"runtime_exceeded"`) |
| Reason emit site | **REUSED (branch update)** | `hvac.py:2310-2311` |
| Duty-cycle constants (window/coast/shed) | **REUSED (promote to knob)** | `hvac_const.py:396-399` |
| Runtime accumulator + counter reset | **REUSED (NO TOUCH)** | `hvac.py:3331-3375`; resets `hvac.py:2955-2969`, `:3564-3590` |
| D3 comfort-delay guard pattern | **REUSED (piggy-back)** | `hvac.py:2026-2053` — the existing per-tick skip block; add the occupancy gate as a sibling clause |
| `_d3_skipped_current_tick` attribute-plumbing pattern | **REUSED as model** | `hvac.py:2083-2086` — new `_d5_occupancy_deferred_current_tick` mirrors this |
| Number-entity knob-persistence machinery | **REUSED** | see `comfort_grace_min` / `comfort_soc_floor_pct` at `hvac.py:713-730` (arrester-backed live rung-3 knobs); mirror the pattern |
| retreat_reason attribute (v5.103.8) | **REUSED** | shipped in the observability cycle; the new deferral reason surfaces there |

**Zero NEW mechanisms proposed** — every deliverable is an extension or a reason-string swap on an existing surface.

### Prior planning docs consulted
- `docs/planning/AUDIT_hvac_duty_cycle_protection_2026_09_17.md` (this cycle's basis; verdict §5).
- README v3.17.0 §D5 (`docs/readmes/README_v3.17.0.md:35-38`) — original ship, no Bryant grounding.
- README v5.103.3 (`docs/readmes/README_v5.103.3.md:34-98`) — S14 removal, distinguishes S14 from D5.
- README v5.103.7/8 (fused `any_room_hvac_occupied` producer; retreat_reason legibility).
- `HVAC-COAST-OBSERVABILITY-1` (kanban.data.yaml:440) — absorbed as D7 of v5.103.8; coast/shed dwell live.
- `HVAC-ZONE-CONDITIONING-DEMAND-1` (step-4-B) — producer of `any_room_hvac_occupied`.

### Memory bodies pulled
- `feedback_tier2plus_prior_art_scan.md` (mandates this section).
- `feedback_coincidental_equality_masks_concept_split.md` (Bug Class #63 — watch for
  runtime-exceeded-vs-coast-savings coincidence).
- `feedback_verify_claim_types_not_felt_uncertainty.md` (Bryant grounding claim was audit-verified
  false; treat "Bryant compressor protection" as a docs-only artifact until proven otherwise).
- `feedback_do_robust_fix_not_bandaid_and_card.md` (fold KNOBS-TO-RUNG-3 rather than card+ship the string swap alone).

### Design docs read
- `docs/reviews/URA_ARCHITECTURE_MAP.md` — HVAC-zone vs house-zone geometry (already load-bearing here).
- `docs/QUALITY_CONTEXT.md` bug classes #7 (stale data source), #22 (enum mismatch), #34 (thread-safety),
  #53 (computed-but-not-consumed), #63 (coincidental equality).

### Code locations surveyed end-to-end
- `hvac.py:1820-2100` (row-4 fused-occupancy branch through D5 guard).
- `hvac.py:2260-2350` (reason ledger precedence + comfort_delay relabel).
- `hvac.py:3331-3375` (runtime accumulator — READ-ONLY in this cycle).
- `hvac.py:2955-2969, 3564-3590, 3843` (runtime_exceeded consumers/resets).
- `hvac_const.py:396-399` (D5 constants).
- `const.py:1262-1300` (HVAC_PRESET_REASONS allow-list).

---

## 2. Falsifiable invariant

> **INV-D5-GATE:** Under `energy_constraint_mode == "coast"`, no zone with
> `zone.any_room_hvac_occupied == True` is written by URA to `preset=away` with
> `preset_change_reason == "coast_duty_limit"` (nor with the legacy
> `"runtime_exceeded"`). Under `energy_constraint_mode == "shed"`, the pre-cycle
> behavior is preserved byte-for-byte (occupied zones remain force-away-eligible
> and continue to emit the shed-labeled reason).

**Discriminating observation** (per `feedback_verification_needs_disjoint_framings`): the invariant
FAILS if any of the following are observed in the URA DB `preset_change` table on the live house:
1. A row with `reason='coast_duty_limit'` AND `zone.any_room_hvac_occupied=True` at emit time
   (captured in `details_json`).
2. A row still emitting `reason='runtime_exceeded'` after the deploy (except from a
   still-live legacy consumer within the compat window — see D2).
3. A row with `reason='shed_duty_limit'` that would NOT have been `runtime_exceeded` under
   the pre-cycle logic (measured against the pre-review baseline tag).

Adversarial framing (Reviewer D): find any code path that reaches
`effective_preset = "away"` due to a runtime_exceeded input while
`zone.any_room_hvac_occupied is True` and `_energy_constraint_mode == "coast"` — the gate
must dominate every such path (there is one today at `hvac.py:2081`, but Reviewer D must
enumerate the full runtime_exceeded consumer surface — §5.1 — and prove no other away-writer
inherits the flag).

---

## 3. Precedence — SHED > OCCUPANCY > COAST-DUTY (recommended)

The audit and the existing D3 code already codify shed dominance
(`hvac.py:2008`: "Shed dominates comfort (rev-2 H3 falsification #6)"). Apply the same rule
here:

```
if runtime_exceeded and house_state != "sleep":
    if _cd_active and not _cd_shed and not _cd_blind and soc >= floor:
        # existing D3 comfort-delay skip (UNCHANGED)
        _d3_skipped_this_tick = True
    elif (not _cd_shed) and zone.any_room_hvac_occupied:                   # NEW D5-OCC GATE
        # COAST + OCCUPIED: DEFER the forced-away
        _d5_occupancy_deferred_this_tick = True
        # do NOT set effective_preset = "away"; fall through
    else:
        # UNoccupied coast OR shed (any occupancy): force away as today
        effective_preset = "away"
```

**Why shed still dominates even when occupied:** shed is the harder grid-stress state (peak
TOU + battery below reserve OR grid event); the operator's standing choice at D3 is to let
shed override comfort. Consistency across D3/D5 is a stronger property than optimizing
occupied-shed comfort — one operator mental model, one dominance rule.

**Operator decision to confirm at the checkpoint (§Operator Checkpoint):** whether
occupancy should ALSO dominate shed. Default proposed = NO (matches D3); if the operator
picks YES, the gate collapses to `if zone.any_room_hvac_occupied: defer` and the shed
comfort-vs-savings tradeoff shifts materially (potentially every shed-tripping zone becomes
comfort-preserved during grid stress).

---

## 4. Deliverables

### D1 — Occupancy gate on D5 forced-away (COAST only, default)

**File / site:** `hvac.py:2026-2081` (the `if zone.runtime_exceeded and not sleep` block).

**Change:** insert the new gate between the existing D3 comfort-delay skip
(`hvac.py:2039-2053`) and the current else-branch's `effective_preset = "away"`
(`hvac.py:2081`). Read `zone.any_room_hvac_occupied` with the same defensive fallback
already used at `hvac.py:1893-1895` (fall back to `any_room_occupied`, then True).

**Per-tick observability:** set `self._d5_occupancy_deferred_current_tick[zone_id] = True`
mirroring the `_d3_skipped_current_tick` plumbing at `hvac.py:2083-2086`. Exposed as an
attribute on the HVAC status sensor next to the existing D3-skip attribute.

**Cross-consumer safety (mandatory — Reviewer C target):** with the gate active,
`runtime_exceeded` is still True but `effective_preset` is NOT "away". Enumerate every
downstream reader of `runtime_exceeded` (§5.1) and confirm each behaves correctly under this
new state:
- `hvac.py:2199` (night-trust suppression details_json echo) — details field, harmless.
- `hvac.py:2213` (vacancy-or-runtime same-write shortcut) — guarded by
  `effective_preset == "away"`; safe (falls through when we defer).
- `hvac.py:2310-2311` (reason ledger) — guarded by `effective_preset == "away"`; safe.
- `hvac.py:2331-2341` (comfort_delay_active relabel) — guarded by `effective_preset != "away"`;
  BUT this branch currently ASSUMES the only reason `runtime_exceeded && !away` is the D3
  skip. After D1, the gate can also produce this state. **Fix required:** extend the
  relabel guard to distinguish D3-skip vs D5-occupancy-defer via
  `_d3_skipped_this_tick` (already there) vs the new `_d5_occupancy_deferred_this_tick`, and
  route the ledger reason accordingly (§D2).
- `hvac.py:2441, 2472` (details_json echoes) — harmless.
- `hvac.py:2955-2969` (post-peak coast RELEASE clears) — unchanged.
- `hvac.py:3564-3590` (window-expiry / mode-transition resets) — unchanged.
- `hvac.py:3843` (sensor-detail read) — extend to expose the deferred state.

### D2 — Reason reframe: `runtime_exceeded` → `coast_duty_limit` / `shed_duty_limit` / `coast_duty_deferred_occupied`

**Files:**
- `const.py:1262-1266` — add the three new members to `HVAC_PRESET_REASONS`; **KEEP
  `"runtime_exceeded"`** in the allow-list for one deploy cycle (backward-compat window)
  and mark it deprecated in the header comment.
- `hvac.py:2310-2311` — replace the flat `"runtime_exceeded"` emit with a branch:
  - `_cd_shed` (shed) → `preset_change_reason = "shed_duty_limit"`.
  - else (coast) → `preset_change_reason = "coast_duty_limit"`.
- `hvac.py:2331-2341` — extend the existing comfort_delay relabel branch to distinguish:
  - `_d3_skipped_this_tick` → `"comfort_delay_active"` (as today).
  - `_d5_occupancy_deferred_this_tick` → `"coast_duty_deferred_occupied"` (new).
- `hvac.py:2286` precedence comment — update; extend `TestReasonLadderPrecedence` (search
  path: `quality/tests/`).
- `hvac.py:2168-2178, 2363-2370` details_json echoes — echo the new labels.
- README write-back (post-deploy).

**Backward-compat:** existing external readers (dashboard? none confirmed — check
`frontend-v3/assets/Zones-*.js`) may match on `"runtime_exceeded"`. The compat plan: the
allow-list keeps the old string one deploy cycle; grep confirms zero HA-facing consumers rely
on it (Reviewer B verifies); the follow-up cycle removes the deprecated member.

### D3 — Rung-3 knobs (absorbs `HVAC-D5-KNOBS-TO-RUNG-3-1`)

Per Numbers-Get-Knobs (CLAUDE.md) — D5 caps + window govern how often URA forces away in
energy events; that is an operator policy, not a safety bound. Rung 3 (Number/Switch entity).

**New knobs (Number/Switch entities), backed by module-constant fallbacks:**

| Knob | Type | Default | Range | Kill-switch semantics | Backed by |
|---|---|---|---|---|---|
| `number.ura_hvac_duty_cycle_window_minutes` | Number | 20 | 5–60 | n/a | `DUTY_CYCLE_WINDOW_SECONDS` (`hvac_const.py:397`) |
| `number.ura_hvac_duty_cycle_coast_pct` | Number | 75 | 0–100 | **0 = coast D5 disabled** | `DUTY_CYCLE_COAST` (`hvac_const.py:398`) |
| `number.ura_hvac_duty_cycle_shed_pct` | Number | 50 | 0–100 | **0 = shed D5 disabled** | `DUTY_CYCLE_SHED` (`hvac_const.py:399`) |
| `switch.ura_hvac_d5_duty_cycle_enable` | Switch | on | — | **off = D5 disabled entirely (accumulator still runs; enforcement gated off)** | new state on coordinator |

**Follow the arrester-live-knob pattern** at `hvac.py:713-730` — a property on `HVACCoordinator`
resolves live from the Number entity, falls back to the module constant when the entity has not
yet seeded. Enforcement reads via the property, never the module constant directly. No changes
to the accumulator (`hvac.py:3331-3375`) — knobs apply only at the cap-compare and
enforcement-consult step.

### D4 — Documentation / README write-back

- Update `hvac_const.py:396-399` header comment: strip any implied compressor-protection
  framing, replace with "URA energy-shed policy — cap on cooling runtime during EC coast/shed;
  Rung-3 operator knobs override these defaults."
- README_v<version>.md: prospective Live section covering the invariant discriminator
  (§Acceptance Criteria).

### Non-goals (explicit)

- **Do NOT touch the accumulator (`hvac.py:3331-3375`) or window math.** The audit found the
  math correct; changing it introduces regression risk to the very energy savings we want to
  preserve.
- **Do NOT rename the internal attribute `zone.runtime_exceeded`** — kept for
  serialization/restore stability (`hvac_zones.py:610, 643, 692`). Only the operator-facing
  reason string changes.
- **Do NOT add a Bryant-spec "compressor cycles per hour" limit.** Audit §3 verdict: URA has
  no manufacturer-grounded compressor duty cycle to enforce; the AC-hard-reset daily cap
  (`hvac_const.py:561`) is the real hardware-protection surface and is out of scope.
- **Do NOT add sleep-exit window reset** here — carded separately as
  `HVAC-D5-SLEEP-EXIT-RESET-1` (contingent on live measurement).
- **Do NOT verify `window_start` restore** here — carded separately as
  `HVAC-D5-WINDOW-START-RESTORE-1`.

---

## 5. Producer / Consumer map (per CLAUDE.md "Producer AND Consumer")

### 5.1 Existing consumers of `zone.runtime_exceeded` — enumerated

| file:line | Role | Behavior after cycle |
|---|---|---|
| `hvac.py:2026` | D3 guard entry (this cycle's site) | Extended to insert D5 occupancy gate |
| `hvac.py:2199` | night-trust suppression details_json | Unchanged (echo only) |
| `hvac.py:2213` | vacancy-or-runtime same-write suppression | Unchanged (guarded by `effective_preset=="away"`) |
| `hvac.py:2310-2311` | reason ledger emit | Rewritten to `coast_duty_limit` / `shed_duty_limit` |
| `hvac.py:2333` | comfort_delay relabel | Extended to distinguish D3-skip vs D5-defer |
| `hvac.py:2370, 2441, 2472` | details_json echoes | Unchanged (echoes) |
| `hvac.py:2955, 2969` | post-peak coast RELEASE clear | Unchanged |
| `hvac.py:3564, 3570, 3590` | window-expiry / accumulator resets | Unchanged |
| `hvac.py:3843` | sensor detail | Extended to also expose deferred state |
| `sensor.py:12805` | sensor detail comment | Update reference |

### 5.2 New/adjusted producers

- **`_d5_occupancy_deferred_current_tick[zone_id]`** — coordinator dict, populated in D1's
  new gate branch, cleared each tick like `_d3_skipped_current_tick`.
- **Live knob properties** — `duty_cycle_coast_pct` / `duty_cycle_shed_pct` /
  `duty_cycle_window_seconds` / `d5_enabled` on `HVACCoordinator` — mirror
  `comfort_grace_min` (`hvac.py:712-720`).

### 5.3 Producer arithmetic health

- `zone.any_room_hvac_occupied` is fused per-room-in-HVAC-zone (v5.103.7 producer). Verified
  live via `hvac.py:1893` where D6 already consumes it; boot-race fallback is
  `getattr(zone, "any_room_hvac_occupied", None)` → `any_room_occupied` → `True`.
- `self.shed_active` (`hvac.py:747-751`) is a straight enum compare against
  `_energy_constraint_mode`; healthy.

---

## 6. Acceptance criteria

### D1 — Occupancy gate

- **Verify:** on `energy_constraint_mode="coast"` with an OCCUPIED zone whose
  `runtime_exceeded=True`, `effective_preset` is NOT rewritten to `"away"` by the D5 branch;
  the zone's existing preset stands.
- **Verify (SHED preservation):** on `energy_constraint_mode="shed"` with an OCCUPIED zone
  whose `runtime_exceeded=True`, `effective_preset` IS rewritten to `"away"` (identical to
  pre-cycle behavior); reason emitted = `"shed_duty_limit"`.
- **Verify (UNoccupied coast preserved):** on coast with an UNoccupied zone whose
  `runtime_exceeded=True`, `effective_preset` is rewritten to `"away"` (energy savings
  preserved); reason emitted = `"coast_duty_limit"`.
- **Sensor:** HVAC status sensor exposes `d5_occupancy_deferred: {zone_id: bool}` attribute.
- **Test:** new `TestD5OccupancyGate` in `quality/tests/` covering the 3-cell matrix (coast
  × occupied, coast × unoccupied, shed × occupied) plus the D3 comfort-delay-skip
  interaction; per-site mutation test that neutering the gate causes exactly the
  coast-occupied cell to fail.
- **Live:** URA DB `preset_change` query 24h post-deploy — zero rows with
  `reason='coast_duty_limit'` AND `details_json.any_room_hvac_occupied=True`; non-zero rows
  with `reason='coast_duty_limit'` AND `any_room_hvac_occupied=False` (proves the gate
  didn't kill coast savings).

### D2 — Reason reframe

- **Verify:** `HVAC_PRESET_REASONS` (`const.py:1262`) contains
  `{"coast_duty_limit", "shed_duty_limit", "coast_duty_deferred_occupied"}`, and (compat
  window) still contains `"runtime_exceeded"`.
- **Verify:** `TestReasonLadderPrecedence` extended to pin the new precedence:
  `stale_occupancy > vacant_past_grace > {coast_duty_limit, shed_duty_limit} > pre_arrival
  > house_state_transition`, with `coast_duty_deferred_occupied` and `comfort_delay_active`
  co-ranked at the D3/D5-defer layer.
- **Sensor:** existing `retreat_reason` attribute (v5.103.8) shows the new strings.
- **Live:** post-deploy DB query — `preset_change` rows with the new reasons appear;
  `runtime_exceeded` count trends to zero (except any transient producer-lag).

### D3 — Knobs

- **Verify:** the four entities appear; setting `coast_pct=0` prevents any
  `coast_duty_limit` emission for a full window; toggling `d5_duty_cycle_enable=off`
  prevents any D5 emission entirely; entity restores across HA restart.
- **Test:** Number-persistence round-trip tests (extend the arrester knob test pattern).
- **Live:** operator sets `coast_pct=0` on a hot evening and confirms no coast-labeled forced
  aways for the window; restores to 75 and confirms behavior returns.

### INV-D5-GATE (post-deploy discriminator)

Single-query DB check within 24h of deploy:
```sql
SELECT COUNT(*) FROM preset_change
 WHERE reason='coast_duty_limit'
   AND json_extract(details_json, '$.any_room_hvac_occupied') = 1;
-- MUST be 0
```

---

## 7. Operator checkpoint (BEFORE build dispatch)

Two decisions the operator owns; both cost/comfort tradeoffs that the code cannot pick.

**Decision 1 — SHED × OCCUPANCY precedence.**
- **Option A (recommended, default):** SHED > OCCUPANCY. Shed still forces occupied zones
  away. Rationale: consistency with D3 comfort-delay (`hvac.py:2008` "shed dominates
  comfort"); shed is the harder grid-stress state.
- **Option B:** OCCUPANCY > SHED. Occupied zones deferred even under shed. Rationale:
  operator wants uniform comfort protection regardless of energy state; accepts higher shed
  cost / grid exposure during evening peaks.

**Decision 2 — Backward-compat window for `runtime_exceeded`.**
- **Option A (recommended):** 1 deploy cycle (`runtime_exceeded` stays in the allow-list
  and is deprecated in comments; removed in the next cycle after a compat grep confirms zero
  external consumers).
- **Option B:** Remove immediately (single-user, no back-compat per
  `project_single_user_no_backcompat.md`).

**Cost/benefit summary for the checkpoint (per Marginal-Benefit Decomposition):**
- Simplest version = D1 (gate) + D2-minimal (branch the reason string). Captures ~all the
  operator complaint: "hot and away in the kitchen during coast".
- Marginal add = D3 knobs. Cost: 4 new entities + arrester-style live-knob plumbing (~120
  LoC + persistence tests). Marginal benefit: kill-switch for the operator to disable coast
  D5 on any hot evening without a code change. Recommended IN because the audit found no
  kill switch exists (§4e).
- Deferred (out-of-scope, carded): sleep-exit reset (contingent on live evidence),
  window_start restore (contingent on grep of `hvac_zones.py:685-700` — could pull in if
  cheap during build, but flag as scope creep).

---

## 8. Plan review requirements (per CLAUDE.md Plan Review — Tier 2)

Before build dispatch:
1. ONE adversarial plan review; reviewer independently re-greps every emission site listed
   in §5.1 and confirms the enumeration; re-runs the `any_room_hvac_occupied` fallback
   verification; challenges the SHED > OCCUPANCY precedence recommendation with a concrete
   grid-cost scenario.
2. Reviewer verifies acceptance criteria discriminate (§6 INV query returns a distinct
   observable under fix vs regression).
3. Reviewer verifies the "compat window" for `runtime_exceeded` is either accepted or the
   operator picked immediate removal (Decision 2).

---

## 9. Verification & deploy steps

1. Pre-review tag: `git tag pre-review-v<version>`.
2. Build D1+D2+D3 in one branch (operator-elevated Tier 2-DB; three reviewers per §0).
3. Post-review baseline diff via `ura-validator`.
4. Deploy via `/deploy` skill.
5. Live Validation (Review D): run the INV-D5-GATE query at T+2h and T+24h.
6. README write-back with observed evidence table (per Record Live Validation Back Into the README).
7. Close card + close absorbed `HVAC-D5-KNOBS-TO-RUNG-3-1`; audit follow-ups
   `HVAC-D5-WINDOW-START-RESTORE-1` and `HVAC-D5-SLEEP-EXIT-RESET-1` remain independently
   tracked.

---

## FINALIZED 2026-09-17 — option (b), per Bryant duty-cycle audit

The Bryant/carrier_api research (`AUDIT_bryant_duty_cycle_redundancy_2026_09_17.md`) resolved the
open shape question: D5 is **PARTIALLY REDUNDANT** — the compressor is natively protected; D5 is
pure energy-shed policy. Build **option (b): reframe + occupancy-gate, do NOT delete.** Operator
directive 2026-09-17: "don't hold it / finish this tail" → the three prior checkpoint decisions are
resolved on recommended defaults (shed-dominates; remove `runtime_exceeded` immediately per
Single-User-No-Back-Compat; absorb the Rung-3 knobs).

### Build spec (the contract)
- **D-b1 (reason rename):** remove `runtime_exceeded`, emit `energy_shed_cap_reached` instead.
  Sites: `hvac.py:2200-2201` (emit), allow-list `hvac.py:2168-2178`, and every precedence/ladder
  reference (`hvac.py:2278-2370`, 2441, 2472, 3843) + the diagnostics attribute keys. No alias.
- **D-b2 (occupancy gate):** at the force-away decision (`hvac.py:1928` and its consumption at
  `~2026`/`2213`/`2310`), when `energy_constraint_mode != "shed"` AND the zone is fused-occupied
  (`zone.any_room_hvac_occupied`, the step-4-B signal), **defer** the force-away and emit reason
  `energy_shed_cap_deferred_occupied`. Under `shed`, preserve today's behavior (shed dominates).
  Reuse step-4-B's shared retreat helper if one exists; do NOT introduce a second occupancy read.
- **D-b3 (knobs → Rung 3, absorbs `HVAC-D5-KNOBS-TO-RUNG-3-1`):** promote
  `DUTY_CYCLE_WINDOW_SECONDS/COAST/SHED` (`hvac_const.py:396-399`) to `Number` entities with the
  existing Number-persistence machinery; add a D5 **enable** switch; `0` on any cap = documented
  kill. Wire through options round-trip + RestoreEntity.

### Invariant (INV-D5-GATE, falsifiable)
"Under `energy_constraint_mode != shed`, no zone with `any_room_hvac_occupied == True` is forced to
`away` by the duty-cap in ANY reachable path." Adversarial pass must break it (incl. the ladder
precedence at 2278-2370 and the comfort-delay interaction at 2319-2333).

### Non-goals (explicit)
- **NOT** re-grounding on ODU Var % — parked as `HVAC-D5-REGROUND-ON-ODU-VAR-1`.
- **NOT** removing D5 (option c) — it stays as an honest coast/shed load-shed lever.
- **NOT** touching `DEFAULT_HVAC_AC_HARD_RESET_DAILY_LIMIT` (the real, correctly-named protection cap).

### Restart-safety
- Reason-string + gate are stateless per tick — safe.
- The Rung-3 Number knobs MUST persist via RestoreEntity (D-b3 acceptance).
- `window_start` restore is a SEPARATE contingent card (`HVAC-D5-WINDOW-START-RESTORE-1`) — verify
  in this build whether the duty counter survives reload; if not, it's a Tier-1 add here.

### Tier / review
Tier 2-DB (presence ↔ HVAC ↔ EC ripple) — 3 framing-disjoint reviews:
A=local-correctness (rename completeness across all 8 sites; no stray `runtime_exceeded`),
B=integration/state-machine (ladder precedence, comfort-delay, shed-dominates, restart),
C=test-authority via real per-site mutation (each rename site + the gate + shed-override each fail a
specific test when neutered) + D adversarial-completeness on INV-D5-GATE.
