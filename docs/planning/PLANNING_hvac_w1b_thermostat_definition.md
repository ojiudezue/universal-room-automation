# PLANNING — HVAC W1-B: Per-brand thermostat definition (Carrier/Bryant first)

**Card:** `HVAC-W1-THERMOSTAT-DEFINITION` (Stage B).
**Tier:** **Tier 3** (delicate, invariant-critical; touches every URA thermostat write in an occupied
house; single-missed-site failures are the exact class §7 state-of-play describes).
**Depends on:** W1-A (`HVAC-SETHVACMODE-CHOKEPOINT-1` + one durable write log). Stage A ships first
so this stage inherits attributable telemetry. **Do NOT dispatch build until Stage A is live and
one clean day of write-log exists** (per state-of-play §11 seq 3).
**Operator posture:** nudges stay ON; AC ramp ON; per-brand behaviour discovered in detail behind a
simple generic interface; explicit operator go required before build AND before deploy (Tier-3
double-checkpoint).
**Reference reads (mandatory for every agent on this cycle):**
`docs/Coordinator/HVAC_ARCHITECTURE_STATE_OF_PLAY.md` (all sections; the §10 corrections ledger
especially), `docs/Coordinator/THERMOSTAT_DEFINITION_CARRIER_BRYANT.md` (companion, ships in the
same cycle as D0).

---

## 0. Falsifiable invariant (state up front — D's target)

> **INV-W1B:** After ANY URA-initiated borrow returns on a Carrier/Bryant zone, the thermostat
> settles on the SNAPSHOT NAMED preset with `hold_activity` equal to that preset, AND URA never
> classifies a Carrier `preset_mode == "manual"` report as a human hold while `hold_activity` names
> a preset (status/config disagreement inside the ownership window is URA's echo — re-assert, do
> not lock out).

Falsification shape: any live episode after this ships in which (a) a nudge / compromise / banking
/ preheat / egress-pause borrow closes and the zone strands in `manual` for > 1 post-write intercept
window (5 min) with `hold_activity != "manual"`, OR (b) `preset_change_locked_out` fires against a
`preset_mode=manual, hold_activity=<named>` snapshot, is a defect. Zero such episodes over a clean
72 h window on all three zones is the ship gate.

**Non-invariants (things this cycle deliberately does NOT promise):**
- Does not eliminate genuine human holds (they still lock URA out — that is correct).
- Does not remove the vendor-schedule race between resume and pin (§6 spec — mitigation, not fix).
- Does not fix `HVAC-COMPOSE-AWAY-THROTTLE-STORM-BLOCKER-1` or
  `HVAC-RESTORE-WRITERS-STRAND-EMPTY-NIGHT-ZONE-1` at the D9 site — those are unblocked by moving
  `_last_emitted_range` ownership INTO the funnel (D2 below).
- Does not add a Nest strategy. Interface shape supports it; code lands only when a Nest is
  available to test.
- Does not attempt to detect who wrote a change (integration doesn't expose it — §7 spec).

---

## 1. Institutional context verified

### 1.1 Prior-art scan (per CLAUDE.md Tier 2+ mandate, elevated to Tier 3 depth)

| Proposed piece | Verdict | Existing at |
|---|---|---|
| Preset-write "resume-then-pin" mechanism | **REUSE** — do not rewrite | `hvac_setpoint.py:288-410` (`emit_set_preset_mode`) + `_needs_resume_first` `:181-226` |
| Capability gate for `resume` | **REUSE** | `hvac_setpoint.py:205-220` |
| `climate.set_temperature` funnel | **REUSE** | `hvac_setpoint.py:229-286` (`emit_set_temperature`) |
| `climate.set_hvac_mode` funnel | **REUSE (from Stage A)** | `emit_set_hvac_mode` (built by `HVAC-SETHVACMODE-CHOKEPOINT-1` in W1-A) |
| Durable per-write log | **REUSE (from Stage A)** | scope in `HVAC-SETHVACMODE-CHOKEPOINT-1` `scope_added_2026_09_25_record_every_write` |
| Excursion primitive (`begin_excursion` / `return_excursion`) | **REUSE** — extend, don't replace | `hvac_excursion.py:766` (`begin`), `:871-1040` (`return`, docstring `:886-888` — "performs NO wire writes; each site emits its own") |
| Per-entity runtime state (`_last_emitted_range`, `_suppressed_until`, `_nudge_pre_preset`, `_override_active`, excursion `_rows`) | **REUSE in place** — state is already keyed by zone_id/entity | `hvac.py:521`, `hvac_override.py:235`, `:262`, `:205`, `hvac_excursion.py:201` |
| Ownership window for post-write echoes | **REUSE + extend** | `hvac_override.py:243-262` `_suppress_kind` provenance (kind-tagged, ~5 s TTL, counter-only consumer today); FIX B2 pre-write preset snapshot `:251-262` (nudge only). Extend to all borrow kinds. |
| Setpoint / preset value classification ("is this URA-owned?") | **NEW** — no such helper today; but see below (uses only existing per-write log values) |
| Per-brand strategy dispatch | **NEW** — minimal (memoized `_strategy_for(hass, entity_id)` per `HVAC-THERMOSTAT-ABSTRACTION-1` `DESIGN_SHAPE_2026_09_16` / `PER_ZONE_CORRECTED_2026_09_16`; stateless functions, NOT per-zone objects) |
| Presets-only borrow-return migration | **NEW** — each of ~11 borrow-return call sites currently writes its own `(setpoints -> preset)` pair; migration means routing every site through the definition |
| No-op write suppression | **NEW helper, REUSE `_last_emitted_range` state** — move ownership from `hvac.py:521` into the funnel |

### 1.2 Prior planning docs consulted (headers or bodies)

- `docs/planning/PLANNING_hvac_governed_excursion.md` — rev-6 banner ("Lease gate STRIPPED; do not
  rebuild it") + kinds enum + `return_excursion` invariant (bookkeeping only). BODY skimmed.
- `docs/planning/PLANNING_hvac_excursion_restore_unified.md` — the parked D2/D3/D4 rework (all
  three CRITICALs from 2026-08-26 four-review). W1-B RESPECTS the parking: does NOT rebuild the
  D2 AST governance gate, does NOT rebuild the D3 manual-preset recovery interlock, does NOT
  re-introduce the S14 off-phase-ceiling token. What it DOES do (presets-only returns, coherence
  check) is disjoint — it removes the MANUAL by construction rather than by post-hoc governance.
- `docs/planning/PLANNING_hvac_live_room_establishment.md` — Stage-0 in-flight; consumers of
  `conditioning_retreat_ok` overlap with the borrow-return sites. W1-B does not change the gate.
- `docs/planning/PLANNING_hvac_zone_conditioning_demand.md`, `..._d5_reframe_occupancy_gate.md`,
  `..._demand_knobs_and_observability.md` — HEADERS only; downstream consumers of preset flips,
  not producers.
- `docs/planning/AUDIT_thermostat_write_paths_2026_09_16` — INVENTORY_2026_09_16 result folded into
  parent card body: set_preset_mode 10/10 funnelled, set_temperature 11/11 funnelled, set_hvac_mode
  7/7 bypassing (Stage A scope).

### 1.3 Memory bodies pulled

- `feedback_extend_existing_never_rebuild.md` — "card + working code ARE the spec". Every REUSE
  above cites its existing symbol.
- `feedback_wire_in_anchor_mandatory.md` — every migrated site gets a behavioral anchor test that
  RED-detects a per-site neutering.
- `feedback_coincidental_equality_masks_concept_split.md` — the `preset_mode == "manual"` vs
  `hold_activity == "manual"` coincidence in the happy path is exactly Bug Class #63; the
  coherence check IS the concept split.
- `feedback_suppression_needs_discharge.md` — every ownership window must have a discharge (TTL
  expiry, coherence match, or explicit clear on named-preset re-read) AND a restart-safe backstop.
- `feedback_mutation_verification_pycache_staleness.md` — mutation drills disable bytecode + clear
  `__pycache__` before every run.
- `feedback_no_soak.md` — validation is one-shot post-restart evidence + a code trip-wire, not a
  72 h calendar reminder. The "72 h clean window" ship-gate above is a query on the write log
  after 72 h have passed, not "watch it".
- `feedback_do_robust_fix_not_bandaid_and_card.md` — the presets-only return is the robust fix
  vs the band-aid of "carry the preset lock knob to expire earlier".
- `feedback_tier2plus_prior_art_scan.md` — this §1 IS the mandated scan.

### 1.4 Design docs read

- `docs/Coordinator/HVAC_ARCHITECTURE_STATE_OF_PLAY.md` — full read (all 345 lines).
- `docs/Coordinator/THERMOSTAT_DEFINITION_CARRIER_BRYANT.md` — companion, ships D0 this cycle.
- `docs/Coordinator/HVAC_COORDINATOR_MANUAL.md` — SKIMMED; superseded by state-of-play for the
  areas this cycle touches.

### 1.5 Code locations surveyed end-to-end

- `custom_components/universal_room_automation/domain_coordinators/hvac_setpoint.py` (funnels).
- `.../hvac_excursion.py` (`begin_excursion` / `return_excursion` + boot audit + kinds).
- `.../hvac_override.py:129-262, :2304-2340, :4339-4650, :5814, :6220` (arrester + suppression +
  nudge start/restore + boot ramp audit + cancel-nudge; the sites this cycle routes through the
  definition).
- `.../hvac_predict.py:976-1560` (banking release / preheat / precool restore sites).
- `.../hvac_egress.py:683/779/795` (pause/resume; the mode sites go through Stage A's funnel).
- `.../hvac.py:2013, :2504-2539, :2674, :2716-2748, :3046` (S1 preset-change + lockout ledger,
  D9 dormant path).
- `/Users/okosisi/ha-config/custom_components/ha_carrier/climate.py` + `const.py` +
  `carrier_data_update_coordinator.py` (behaviour cited in the companion doc).

---

## 2. Deliverables

Each deliverable is separately mutation-anchored and separately shippable. Order matters — a
big-bang migration is what put S14 into the world (per parent card).

### D0 — Companion definition doc (SHIPS THIS CYCLE)
`docs/Coordinator/THERMOSTAT_DEFINITION_CARRIER_BRYANT.md` (already drafted). Any behaviour claim
in the strategy code cites a section here.

**Acceptance:**
- **Verify:** every strategy branch has a `# see THERMOSTAT_DEFINITION_CARRIER_BRYANT.md §N` cite.
- **Verify:** every UNVERIFIED item in the companion doc §9 is either resolved before ship or
  carried forward as a documented open question.

### D1 — Generic strategy interface (behaviour-neutral)

A stateless module `domain_coordinators/hvac_strategy.py` (new file) that exposes:

```
strategy_for(hass, entity_id) -> Strategy         # memoized by entity_id (NOT per-zone object)
Strategy.hold_named_preset(hass, entity_id, preset, snapshot=..., zone_id=..., reason=..., site=...)
Strategy.begin_borrow(hass, entity_id, kind, snapshot=..., zone_id=..., reason=..., site=...)
Strategy.return_borrow(hass, entity_id, snapshot=..., zone_id=..., reason=..., site=...)
Strategy.read_observed_hold(hass, entity_id) -> HoldObservation
Strategy.classify_manual(hass, entity_id, observed: HoldObservation) -> HoldClassification
```

`HoldObservation` = `{preset_mode, hold_activity, target_high, target_low, hvac_mode, read_at}`.
`HoldClassification` ∈ `{NAMED, HUMAN_MANUAL, URA_ECHO_MANUAL, URA_OWNED_MANUAL, STALE_MANUAL}`.

`Strategy` is a dispatch surface, not per-zone state. Implementations are stateless functions
parameterised by `entity_id`. All per-entity runtime state (last-emitted, suppression, snapshot)
stays where it already lives (per prior-art scan) — the strategy READS/WRITES those existing
stores, does not shadow them.

**D1 ships behaviour-neutral:** the initial `hold_named_preset` implementation is the CURRENT
`emit_set_preset_mode` behaviour, lifted through the strategy indirection. Same for `set_temperature`
under `begin_borrow`. `classify_manual` initially returns whatever URA's current code decides. This
lets D2/D3 land site-by-site.

**Acceptance:**
- **Verify:** every existing `emit_set_preset_mode` / `emit_set_temperature` caller behaves
  byte-identically. Test = name-diff on the full suite; ONE new module, zero behaviour change.
- **Test:** `test_strategy_dispatch_carrier` — a Carrier entity_id returns the Carrier strategy;
  an entity with unknown domain returns the generic default.
- **Test:** `test_strategy_memoization_by_entity_id` — same entity_id -> same instance; different
  entity_id -> different instance.
- **Live:** post-restart, one grep confirms every borrow-return site imports through
  `hvac_strategy`; no bypass verb calls remain outside the funnels (Stage A already achieved this
  for the three verbs).

### D2 — Carrier strategy: presets-only borrow return + coherence + reclaim + no-op suppression

Concrete `CarrierStrategy` for domain `ha_carrier`:

1. **`hold_named_preset` = clear-then-pin** — lift the existing resume-then-pin. Cite spec §1, §6.
2. **`return_borrow` = presets-only** when the snapshot preset is a named profile. Cite spec §6
   invariant. The named profile carries its own setpoints; no preceding `set_temperature` write.
   **All ~11 borrow-return sites route their return through `Strategy.return_borrow`.** The site
   still calls `return_excursion` for bookkeeping (kind, restore_ok, NM latch) but the wire writes
   are inside the strategy. This is the migration cost the operator brief calls out: every site
   is touched.
3. **`classify_manual`** implements the coherence rule (spec §4.3, §6):
   - `preset_mode != "manual"` -> `NAMED`.
   - `preset_mode == "manual" AND hold_activity == "manual"`:
     - inside a URA post-write ownership window whose snapshot setpoints match the observed
       setpoints -> `URA_ECHO_MANUAL`.
     - snapshot setpoints match observed BUT window has expired AND age < reclaim knob (see D4) ->
       `URA_OWNED_MANUAL`.
     - observed setpoints equal a named-preset comfort profile -> `STALE_MANUAL`.
     - otherwise -> `HUMAN_MANUAL`.
   - `preset_mode == "manual" AND hold_activity` names a preset -> `URA_ECHO_MANUAL`
     (status-vs-config disagreement inside post-write intercept window is by construction URA's
     echo; spec §5).
4. **S1 (`hvac.py:2013, :2674`) consumes `classify_manual`** — treat only `HUMAN_MANUAL` as the
   lockout case. `URA_ECHO_MANUAL` / `URA_OWNED_MANUAL` / `STALE_MANUAL` all re-assert the
   snapshot preset via `hold_named_preset`.
5. **Ownership window (extend `_suppress_kind`)** — every strategy write records `(entity_id,
   verb, values, snapshot_preset, wrote_at)` into an in-memory ownership dict keyed by
   `entity_id`. Window length = existing suppress TTL plus one post-write intercept window
   (`ha_carrier` `POST_WRITE_INTERCEPT_WINDOW_MINUTES = 5`, spec §5). Restart-safe: if the dict
   is empty on boot, classification errs toward `STALE_MANUAL` for setpoints matching a named
   profile, so no cold-start human-override false page.
6. **`_last_emitted_range` moves INTO the funnel**, keyed by `(entity_id, verb)`. Any writer
   emitting the same values as the last-sent record is suppressed at the funnel with a debug
   log. THIS IS THE FIX FOR `HVAC-COMPOSE-AWAY-THROTTLE-STORM-BLOCKER-1` and
   `HVAC-RESTORE-WRITERS-STRAND-EMPTY-NIGHT-ZONE-1`: once ownership sits in the funnel, the
   unconditional bypass at D9 (`hvac.py:2966`) and the un-invalidating restore writers
   (`hvac_override.py:5814/6220`, `hvac_predict.py:976/1507`) all become correct-by-construction.
   Remove those sites' local caches after migration.

**Acceptance:**
- **Verify:** all 11 borrow-return sites (enumerate independently in D-review, not this doc):
  after the site's return path, no `set_temperature` service call is emitted; the preset call
  lands with the snapshot preset. Discriminator = flip snapshot preset in a test; the emitted
  preset must follow the snapshot, not a hard-coded value.
- **Sensor:** `ura_activity_log` row `preset_change` count per zone per day drops materially
  after ship (state-of-play §9.1 baseline: zone_1 88 manual entries / 130 h). The clean 72 h
  gate is < 5 URA-caused manuals per zone.
- **Test:** `test_carrier_return_presets_only[all 11 sites]` — one per site, each mutating the
  strategy's `return_borrow` in one site's call graph and confirming the site-specific test goes
  RED. (Tier-3 C framing = per-site production-source mutation.)
- **Test:** `test_classify_manual_matrix` — a table of `(preset_mode, hold_activity, setpoints,
  ownership_window_state)` producing each `HoldClassification`. Table MUST include the four
  measured strand shapes from state-of-play §9.1 (09-21 12:53, 09-22 01:19, 09-24 19:57,
  09-25 14:22) as fixtures.
- **Test:** `test_no_op_write_suppression_at_funnel` — a repeat write with identical values
  emits zero service calls; a write with a differing value emits one.
- **Test:** `test_ownership_window_restart_safe` — after `hass.async_stop()` and a fresh setup,
  a subsequent `manual` observation whose setpoints match a named profile classifies as
  `STALE_MANUAL` (reclaim), not `HUMAN_MANUAL` (lockout).
- **Live:** grep `preset_change_locked_out` in `ura_activity_log` over 72 h post-deploy — target
  ≤ 3 rows / zone / day; and every row's snapshot has `hold_activity == "manual"`.

### D3 — Hold-timeout that actually releases

Per operator challenge 2026-09-25 ("we have a knob that says don't override till next change, and
that knob times out"): the existing Temp Arrester Override, immune-person hold, and Comfort Grace
knobs only hand back to the arrester — they do not release the lockout because the arrester declines
on zero delta (state-of-play §7).

D3 wires each expiring knob to a **strategy-level release**: on expiry, if `classify_manual` returns
`URA_OWNED_MANUAL` or `STALE_MANUAL`, issue `hold_named_preset(snapshot)`. `HUMAN_MANUAL` is still
respected.

**Acceptance:**
- **Verify:** each of Temp Arrester Override, immune-person hold, Comfort Grace expiring against a
  URA-owned or stale manual produces one `hold_named_preset` call within one decision cycle.
- **Test:** `test_knob_expiry_reclaims_stale_manual` (one per knob).
- **Live:** the four historical strand cases in §9.1 would each have cleared within one tick after
  the earliest matching knob expiry — verify via write-log replay against a fixture built from the
  recorder.

### D4 — Reclaim age knob (numbers on the ladder)

**Rung 3 (Number entity) — `number.ura_hvac_coordinator_ura_owned_manual_reclaim_min`:**
window after a URA write during which a `URA_OWNED_MANUAL` observation is reclaimable. Default
30 min. RestoreEntity, live-tunable via dashboard. Kill-switch semantics: set 0 = disable reclaim
(feature off for that surface). Rationale for Rung 3: the operator legitimately tunes this by
observation (spec §5 lag varies with cloud traffic); it's not a safety bound. If unset, feature
uses default; if set to 0, no reclaim (only expiring knobs release, per D3).

**Rung 1 (module const) — `CARRIER_POST_WRITE_INTERCEPT_S = 300`:**
matches ha_carrier's own window (spec §5). Change requires review (it is a protocol constant, not
a policy).

**Rung 1 (module const) — `NAMED_PROFILE_MATCH_TOLERANCE_F = 0.1`:**
setpoint equality tolerance for matching a manual profile to a named comfort profile (rounding /
unit conversion safety). Review-only.

**Acceptance:**
- **Verify:** the entity persists across restart (RestoreEntity).
- **Verify:** setting to 0 disables reclaim (no `URA_OWNED_MANUAL` reclaim path fires) while
  leaving `URA_ECHO_MANUAL` and D3 knob-expiry paths intact — discriminating test.
- **Live:** `number.ura_hvac_coordinator_ura_owned_manual_reclaim_min` exists post-restart with
  default 30 (or last-set value); reads via options round-trip.

### D5 — Generic default strategy

For any thermostat NOT in the seed table (only `ha_carrier` today):
- `hold_named_preset` = direct pin (no clear; no vendor knowledge).
- `begin_borrow` / `return_borrow` = setpoints then preset (today's behaviour).
- `classify_manual` = always `HUMAN_MANUAL` when `preset_mode == "manual"` (no coherence
  assumption without vendor knowledge).
- `read_observed_hold` reads standard climate attributes; `hold_activity` may be absent (returns
  `None`).

**Acceptance:**
- **Test:** `test_generic_strategy_no_clear_no_reclaim` — a stub non-Carrier entity gets a direct
  pin; classify always returns HUMAN_MANUAL for manual. This DISCRIMINATES the two strategies —
  passes only if the abstraction is wired (per parent card
  `HVAC-PRESET-WRITE-STRATEGY-1.DESIGN_DETECT_VS_SPECIFY_2026_09_16` invariant).
- **Non-goal:** no Nest strategy code. Interface accepts one; no speculative implementation.

### D6 — Migration hygiene: remove duplicated per-site restore code

After D2 is live and each site's mutation test proves the site routes through
`Strategy.return_borrow`, remove each site's now-dead in-line `(setpoints -> preset)` return
sequence. This is the "eleven copies" the operator brief calls out.

**Acceptance:**
- **Verify:** `git grep` post-D6 finds no direct `set_temperature`+`set_preset_mode` return pair
  at any of the 11 sites — all removed.
- **Test:** the D2 per-site mutation tests still RED under D6 (i.e. the removal did not accidentally
  break the routing).

---

## 3. Config-boundary / combinatorial matrix (Tier-3 mandate)

Independent knobs: `infinite_holds` (True live), reclaim window (0..∞), post-write intercept (5
min const), suppression TTL (~5 s), snapshot preset (`home`/`away`/`sleep`/`wake`/`vacation`/`manual`),
observed `preset_mode` (any of the above + `resume`), observed `hold_activity` (any of the above
or `None`), setpoint match state (matches snapshot / matches other named profile / matches
neither), window state (inside intercept / inside reclaim / outside both).

Reviewers MUST test at least these EXTREMES + INVERSIONS:
- `reclaim_window = 0` (feature disabled) with a `URA_OWNED_MANUAL` observation — must NOT reclaim.
- `reclaim_window >> intercept_window` — `URA_OWNED_MANUAL` reclaims after intercept expires.
- `snapshot preset == "manual"` (the pre_preset==manual case that hosed D1-only) —
  `return_borrow` MUST NOT presets-only against a manual snapshot; falls back to the direct
  setpoints+preset return.
- `hold_activity == None` on an entity that doesn't expose it (generic strategy).
- `preset_mode == "manual"` while `hold_activity == "home"` outside every window — this is the
  spec §5 stale case; classify as `STALE_MANUAL` and reclaim, do NOT lock out.
- `preset_mode == "resume"` transient during a clear-then-pin — classify as transient, no action.

---

## 4. Review protocol (Tier 3 — 4 framing-disjoint reviews + orchestrator verification)

Per CLAUDE.md Tier 3 + operator standing policy (all regression-prone HVAC work runs the 3-disjoint
framings; this cycle adds the 4th adversarial-completeness pass because W1-B threads a shared
primitive across ~11 sites — the exact `HVAC-EXCURSION-RESTORE-UNIFIED-1` failure shape).

- **Reviewer A — local correctness** (strategy branch logic per verb; classify_manual matrix
  arithmetic; presets-only return per site).
- **Reviewer B — integration / state-machine integrity** (post-write ownership window discharge,
  restart safety, no double-emit under sweep re-entrancy, no regression on `HUMAN_MANUAL`
  lockout, no interaction with the parked D2/D3/D4 governance work).
- **Reviewer C — test authority via REAL per-site source mutation** (each of the 11 borrow-return
  sites gets its own mutation; global monkeypatch is NOT sufficient — that is exactly the
  hollow-anchor failure `feedback_hollow_test_anchors.md` and the v5.5.3 D-HIGH-1 lesson).
  Bytecode disabled + `__pycache__` cleared each drill.
- **Reviewer D — adversarial completeness / diff-blind** (restate INV-W1B in the reviewer's own
  words; re-enumerate the ENTIRE thermostat-write surface across `hvac*.py` — INCLUDING
  pre-existing code, not just the diff — for any missed borrow-return site, any writer that still
  bypasses the strategy, any classifier consumer that reads `preset_mode == "manual"` directly
  without going through `classify_manual`).

**One plan review (this doc) before build dispatch** per Tier 3 (two plan reviews required):
- **Plan-Reviewer 1 — completeness:** independently re-enumerate the borrow-return sites (this
  doc's "~11" is a hypothesis, not a spec); verify every parked-plan trigger this cycle would
  fire; verify the strategy interface covers every capability the 11 sites need.
- **Plan-Reviewer 2 — build-prediction:** predict what a builder gets wrong reading this. Any
  ambiguity or "either X or Y" is a finding. In particular: is the migration ordering explicit
  enough? does the ownership-window discharge specify EVERY release path? is
  `_last_emitted_range` ownership move sequenced against the D9 dormant switch state?

**Orchestrator hand-check before deploy (Tier-3 mandate):**
1. `git grep` re-run of every `climate.set_temperature` / `climate.set_preset_mode` call outside
   the funnels — count MUST be zero.
2. Re-run of the enumerated 11-site list against the strategy — every site must map to a
   `Strategy.return_borrow` call.
3. Real source mutation of `Strategy.return_borrow` — the full suite must go RED with a specific
   named failure per site.

**Operator checkpoint BEFORE deploy** (Tier-3 mandate; also implied by operator standing
"nudges stay ON" and Carrier-cloud-write sensitivity): surface D-review outcome, the invariant
proof (grep + mutation), and the enumerated 11-site coverage. Get explicit go.

---

## 5. Sequencing / dependencies

1. Stage A ships (`HVAC-SETHVACMODE-CHOKEPOINT-1` + write log). One clean day of write-log data
   is captured — used to seed the D2 fixture table.
2. This planning doc gets its two plan reviews. Findings folded in place before build dispatch.
3. Build in isolated worktree `.claude/worktrees/hvac-w1b-thermostat-definition` on branch
   `feature/hvac-w1b-thermostat-definition` off latest `develop`.
4. Build order: **D0 (already drafted, small update if UNVERIFIED items resolved) -> D1
   (behaviour-neutral) -> D4 (knob + module consts) -> D5 (generic default; small) -> D2
   (Carrier strategy behaviour + site migration) -> D3 (knob expiry release) -> D6 (cleanup).**
   D2 is the load-bearing step. D6 lands only after live validation of D2 across all 3 zones for
   ≥ 24 h.
5. Four framing-disjoint reviews on the D0-D5 build in parallel. Fix CRITICAL/HIGH; re-run
   D's enumeration; orchestrator hand-check.
6. Operator checkpoint. On go: deploy.
7. Live-validation write-back into README as post-deploy validation table (state-of-play recording
   discipline).
8. D6 dispatched as a separate small cycle once D2 is confirmed live-clean.

**No soak.** Ship gate at 72 h is a one-shot query against `ura_activity_log` +
`hvac_excursion_events` at disposition time, not a calendar watch.

---

## 6. Open operator questions (please answer before build dispatch)

1. **`set_activity_setpoint` as a no-hold nudge path** — spec §3 flags the interrupted-edit
   hazard (a partially applied nudge permanently changes the named comfort profile). Do we
   adopt this for nudges in W1-B, or keep nudges on `set_temperature` (today's path) and treat
   `set_activity_setpoint` as future work behind its own evidence trigger? Default recommendation
   per Marginal-Benefit rule: **KEEP nudges on `set_temperature`**; the presets-only return + the
   coherence classifier remove the actual observed harm without introducing a new risky
   ingredient. Park `set_activity_setpoint` with the trigger "if a measured post-nudge lag
   window causes real cost."
2. **Bryant schedule scope** — the state-of-play working assumption is that schedules are being
   reduced so URA alone controls. Zones 2/3 still run 4-entry schedules. Do we depend on further
   schedule reduction to eliminate the resume-vs-vendor race on zones 2/3, or should the Carrier
   strategy add a schedule-boundary guard (skip resume-then-pin within N seconds of
   `next_activity_time`)? Default recommendation: **operator continues schedule reduction; no
   schedule-boundary guard in W1-B** (it's a workaround for a self-inflicted problem the operator
   can solve outside URA).
3. **Reclaim knob default** — 30 min is a guess based on the observed strand medians in §9.1
   (median 5.1 min restore-lockouts, longest 661 min). Should default be 30 min (aggressive) or
   60 min (conservative)? Recommendation: **30 min** — the failure mode of an over-eager reclaim
   is a redundant preset write on a genuinely-idle-human hold, which is small; the failure of
   an under-eager reclaim is exactly what we're fixing.
4. **Ship gate — 72 h clean vs shorter** — state-of-play §9.1 covered ~130 h to build the fixture
   table. 72 h post-deploy is a reasonable measurement window. Operator willing to hold the ship
   verdict for 72 h of write-log accumulation, or shorter? Default: **72 h** — the strand shapes
   are ≥ 1 h apart in nature.
5. **Nest interface stub** — the interface shape supports Nest; do we land a `NestStrategy`
   placeholder module that raises `NotImplementedError` at construction, or skip Nest entirely
   until there is one to test? Default recommendation: **skip** — a placeholder invites
   speculative filling.
6. **D4 rung placement for `NAMED_PROFILE_MATCH_TOLERANCE_F`** — proposed Rung 1 (module const)
   as a review-only knob. Operator agree, or is this legitimately a Rung 3 tunable?
