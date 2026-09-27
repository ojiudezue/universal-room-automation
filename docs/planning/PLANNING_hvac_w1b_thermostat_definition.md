# PLANNING — HVAC W1-B: Per-brand thermostat definition (Carrier/Bryant first) — REV 4

**Card:** `HVAC-W1-THERMOSTAT-DEFINITION` (Stage B).
**Tier:** **Tier 3** (delicate; threads a shared primitive across ~10 return sequences; a single missed site is the exact failure class the parked `HVAC-EXCURSION-RESTORE-UNIFIED-1` cycle exhibited; adds a borrow-lock that suppresses S1 and the arrester and MUST have a bounded discharge; adds a provenance primitive that decides whether a manual-looking hold is URA-owned or human).
**Depends on:**
- W1-A (`HVAC-SETHVACMODE-CHOKEPOINT-1` + one durable write log) — **SHIPPED v5.103.16 2026-09-26** (`docs/readmes/README_v5.103.16.md`). `climate_write` records `values_before` (incl. `preset_mode` AND `hold_activity` read synchronously pre-write) + `values_after` + `wire_ok` + `site` / `zone_id` / `reason` / `excursion_id` / `ts_issued` / `ts_returned`.
- Arrester echo-window fix (`HVAC-ARRESTER-NUDGE-ECHO-FALSE-OVERRIDE-1`, `SUPPRESS_TTL_SECONDS` 5→15, kind="temp" only) — **shipping v5.103.17 2026-09-27**. **D0 strand-window measurement gates on ≥ 2 days of post-v5.103.17 data.**
**Operator posture:** nudges stay ON; AC ramp ON; per-brand behaviour discovered in detail behind a simple generic interface; Tier-3 double-checkpoint (before build AND before deploy).
**Reference reads (mandatory, complete, before doing anything):**
`docs/Coordinator/HVAC_ARCHITECTURE_STATE_OF_PLAY.md` (all sections — especially §6, §7, §9.1, §9.7, and §10 C17 / C20-C24),
`docs/Coordinator/THERMOSTAT_DEFINITION_CARRIER_BRYANT.md` rev 2 (companion),
`docs/readmes/README_v5.103.16.md` (climate_write ledger row shape) + `docs/readmes/README_v5.103.17.md` (echo-window fix),
current REV 3 of this file (superseded by REV 4 below), and the two REV-3 plan reviews' findings (summarised inline where folded).

---

## Rev-4 change log — WHY REV 4 exists

The operator (2026-09-26 evening) cut the cycle scope to **problems 1, 2, 3, 5** and removed the confirmation-oracle work (problem 6) and the knob-expiry reclaim work (problem 4). Confirmation-oracle work becomes a separate measurement-only investigation (card `HVAC-WRITE-CONFIRMATION-ORACLE-1`, being minted by the orchestrator); knob-expiry reclaim is PARKED with a revival trigger (data refuted the harm hypothesis — 22 automatic Temp-Arrester-Override / immune-person expiries since 2026-08-28, 0 `preset_change_locked_out` rows within 3 h; preset changes resume normally). This scope cut removes the load-bearing REV 3 addition (`Strategy.confirms()` / D2.7 oracle DATA) and lets REV 4 concentrate on the borrow-lock, the provenance last-write record, and the URA-owned reclaim path that binding decision 3 governs (the reclaim DELAY + separate kill switch — NOT removed with D3; the reclaim is problem 1 / 5 IN scope).

REV 4 also folds the operator's five new binding decisions (8-12) and the surviving findings from the two REV-3 plan reviews (summary at the top of §1.4).

| Change | Where folded |
|---|---|
| Scope cut to problems 1/2/3/5; problem 6 REMOVED; problem 4 REMOVED + PARKED | §0.1, §2, §4, §5 (D2.7 removed; former D3 knob-expiry reclaim removed) |
| Decision 7 (REV 3) has no consumer this cycle | §6 note under old Q7 |
| Decision 8 (scope) | §0.1, §2, §4 |
| Decision 9 (borrow lock only on nudges + compromises; hard cap 10 min; lock derived from LIVE borrow state — `_rows[zone_id]` and `_nudge_excursion_tokens` / `_nudge_restore_timers`, NOT `_override_active`, NOT non-existent `hvac_excursion_state` columns) | §5 D2.1 replaced |
| Decision 10 (a genuine human change during a locked borrow ENDS the borrow with NO return write; must use echo-safe detection — after the 15 s temp window) | §5 D2.1 human-ends-borrow path; §5 D2.4 return contract carve-out; explicit fix to `hvac_override.py:4674-4685` which today skips the corrective-writes gate |
| Decision 11a (presets-only returns on EVERY real return path; verified inventory refreshed against current develop; row 1322 STAYS no-write) | §5 D2.4 |
| Decision 11b (in-memory W1-A last-write record per entity — verb, APPLIED values post freeze-floor/deadband, issue wall-time — exposed as small read API; ±0.5 °F tolerance; strand window sized from data ~300-370 s post `nudge_restored` per echo-fix review B; MUST NOT rely on `override_detected` alone for human evidence — explicit discriminator) | §5 D2.3 provenance primitive |
| Decision 12 (CONFIG-FIRST proof — no setting fixes problems 1/2/3/5) | new §0.2 |
| **Binding decision 3 RESTORED (orchestrator correction 2026-09-26)** — `URA_OWNED_MANUAL` reclaim DELAY + separate kill switch was WRONGLY dropped with D3 in the first REV 4 pass. Decision 8 removed problem 4 only (knob-expiry reclaim). Decision 3 governs the reclaim of URA-OWNED manual holds via the provenance path, which IS problem 1 / 5 and IS in scope. | §5 D2.3 URA-owned reclaim path; §5 D4 constants (1-tick delay + kill switch); §0 INV C6; §7 ship gate C6 |
| REV-3 review — tri-state write funnel result (APPLIED / SKIPPED_ALREADY_CORRECT / FAILED) + 28-site table (site × verb × Strategy method or direct-funnel-with-reason × gates) | §5 D1 (WriteResult) + §5 D2.8 (28-site table) |
| REV-3 review — D1 truly behaviour-neutral (where resume-then-pin lives; exempt W1-A `_snapshot_climate_state`) | §5 D1 explicit note |
| REV-3 review — D5 generic default fully specified | §5 D5 unchanged from REV 3 (kept, oracle-trivial branch DELETED — see D1) |
| REV-3 review — stale line citations refreshed against current develop | verified 2026-09-26 |
| REV-3 review — every `preset_mode` trust reader routes through `Strategy.classify`; grep-only completeness test REPLACED per orchestrator correction with a behavioural per-site anchor + AST-based completeness lint (Bug Class #62 — source grep is not a test) | §5 D2.6 rewritten |
| REV-3 review — retry / no-op semantics limited to what problems 1/3 need (no confirmation oracle, no bounded retry, no CONFIRMATION_* constants) | §5 D2.5 (no-op only); D4 constants list cut of confirmation-oracle consts |
| Falsifiable invariant rewritten for the new scope (each conjunct individually falsifiable + a matching §7 disposition-query row) | §0 (six conjuncts C1-C6) |
| Ship gate + 4-framing review + orchestrator hand-check + operator checkpoint retained | §7, §8 |

REV 3's rev-2 and rev-1 fold tables are preserved as provenance in the git history of this file (git log shows the REV 3 body); not re-copied here.

**Orchestrator correction re-review (2026-09-26 evening):** three findings from the orchestrator's review of the first REV 4 draft — (a) restore binding decision 3's reclaim delay + kill switch (this cycle's problem 1 / 5 reclaim path, distinct from the parked D3 knob-expiry reclaim); (b) replace the D2.6 grep-only completeness test with a behavioural per-site anchor + AST lint (Bug Class #62); (c) keep the reference to `HVAC-WRITE-CONFIRMATION-ORACLE-1` (being minted by the orchestrator now, not previously carded) — all folded in this revision.

---

## 0. Falsifiable invariant (state up front — reviewer D's target)

> **INV-W1B (REV 4).** On a Carrier/Bryant zone, over the ship-gate exercised-episode floor (§7):
>
> **C1 (presets-only return).** Every URA-initiated borrow return sequence (§5 D2.4)
> emits ZERO `climate.set_temperature` calls in its return, EXCEPT when the return's snapshot is
> a `HUMAN_MANUAL` classification (INV carve-out); this is enforced by per-site service-call-count
> tests AND by the D1 tri-state `WriteResult.reason` of every return-path call.
>
> **C2 (borrow-lock coverage, bounded).** While a NUDGE or COMPROMISE borrow is live for an
> entity (`_rows[zone_id]` open with `kind ∈ {NUDGE, COMPROMISE}` OR
> `_nudge_excursion_tokens[zone_id]` present OR `_nudge_restore_timers[zone_id]` scheduled),
> S1 (`hvac.py:2674`) and the arrester (`hvac_override.py:2304-2340`) emit ZERO writes to that
> entity, EXCEPT (a) the borrow's own return writes carrying the live token's `excursion_id`,
> and (b) after `BORROW_LOCK_HARD_CAP_S = 600` since lock arm, the lock ENDS, one NM
> `[BORROW LOCK CAP HIT]` is emitted for that entity, and normal writers resume for that
> entity's next tick. Banking, pre-cool, pre-heat, egress are NEVER locked (long by design;
> the rev-6 lease gate was stripped for this exact reason — do not rebuild it).
>
> **C3 (human ends a locked borrow, no return write).** A genuine human change detected on an
> entity while its borrow-lock is armed ENDS that borrow with NO return write (the pre-nudge
> setpoint / snapshot preset are NOT written back). "Genuine" = per §5 D2.3 discriminator
> (echo-safe: detection only after the 15 s temp-kind suppression window; distinct from an
> `override_detected` row alone). Today's nudge restore
> (`hvac_override.py:4617-4700+`, incl. its `_corrective_writes_suppressed` exception at
> `:4622-4640`, `:4674-4685`) intentionally writes the pre-nudge setpoint over a person in
> the 2 min window; REV 4 fixes that for the locked borrow kinds.
>
> **C4 (URA-owned classification by provenance, not by `override_detected` alone).** For any
> observed manual hold on a zone: if the ProvenanceStore (§5 D2.3) has an in-window W1-A
> `climate_write` for that entity whose `values_after` matches the observed setpoints within
> `URA_OWNED_TOLERANCE_F = 0.5` (device displays whole degrees, tolerance ≥ half a unit) AND
> the `hold_activity` reading appeared AFTER URA's last write AND no genuine human change
> (§5 D2.3 discriminator) fell in the interval, the hold is `URA_OWNED_MANUAL` and S1 is NOT
> locked out for that observation.
>
> **C5 (no-op suppression at the funnel).** The funnel returns `SKIPPED_ALREADY_CORRECT` when
> intended `(verb, values)` equal the funnel's last-sent record for the entity AND the observed
> state equals those values; that path emits ZERO service calls. Any actual write to the entity
> clears the record; any observed divergence from the record clears it. **NO confirmation
> oracle** and **NO bounded retry** — a real disagreement between STATUS and CONFIG feeds is
> out of scope this cycle and belongs to the separate measurement-only investigation
> (`HVAC-WRITE-CONFIRMATION-ORACLE-1`).
>
> **C6 (URA-owned reclaim is prompt but bounded — binding decision 3).** When
> `URA_OWNED_MANUAL` is classified (C4), `BORROW_LOCK` is inactive, `_corrective_writes_suppressed`
> is False, AND the reclaim kill switch (`switch.ura_hvac_coordinator_ura_owned_manual_reclaim_enabled`)
> is ON: the reclaim writes S1's current target within `URA_OWNED_RECLAIM_DELAY_S + 1 tick`
> (default delay = 0, same-tick eligible). With the kill switch OFF, no reclaim fires and S1
> behaves as today (lockout on manual). Binding decision 3 (2026-09-26): *"Reclaim DELAY for a
> URA-owned manual hold with no live borrow = 1 tick (same-tick eligible), plus a separate kill
> switch."*

### Falsification shape per conjunct (matched 1:1 to §7 ship-gate query rows)

| Conjunct | Falsifier query at disposition time |
|---|---|
| C1 | Any `climate_write` row with `verb=set_temperature`, `site` matching a §5 D2.4 return site, and `reason` NOT indicating HUMAN_MANUAL snapshot. |
| C2 | Any `climate_write` row into an entity while a NUDGE/COMPROMISE excursion `_rows[zone_id]` was open (join by `entity_id` + interval) with `excursion_id` NOT matching the live token, absent the `[BORROW LOCK CAP HIT]` NM latch preceding it. |
| C3 | Any restore write inside the borrow-lock window where `override_detected` OR a genuine human change (per §5 D2.3) was observed on the same entity after lock arm and BEFORE the restore. |
| C4 | Any `preset_change_locked_out` row on an entity where the immediately preceding W1-A `climate_write` on that entity matches the observed manual setpoints within `URA_OWNED_TOLERANCE_F` AND `hold_activity` post-dates URA's write AND no genuine human change (§5 D2.3) occurred in the interval. |
| C5 | For any `climate_write` row with `wire_ok=True` and identical `values_before`==`values_after` (i.e. wire fired despite no change): count > 0. |
| C6 | Given kill switch ON: for each `URA_OWNED_MANUAL` classification with no live borrow and no corrective-writes suppression, count of intervals from classification to the reclaim `climate_write` on the entity that exceed `URA_OWNED_RECLAIM_DELAY_S + 1 tick`; MUST be 0. Given kill switch OFF: count of reclaim writes on `URA_OWNED_MANUAL` classifications; MUST be 0 (i.e. behaves as today, S1 locks out). |

**INV carve-outs (explicit non-invariants):**
- A genuine `set_temperature` by a human (dial or app) at values URA did not write is NOT
  URA-owned — those still lock URA out (correct behaviour).
- Named-vs-named STATUS↔CONFIG disagreement (§9.7) — REMOVED from this cycle; the write-churn
  on that surface is the measurement-only investigation's problem, not W1-B's.
- Vendor-schedule race between `resume` and `pin` may still cause a brief unwanted state; not
  this cycle's invariant.
- `HVAC-COMPOSE-AWAY-THROTTLE-STORM-BLOCKER-1` and `HVAC-RESTORE-WRITERS-STRAND-EMPTY-NIGHT-ZONE-1`
  are unblocked by moving `_last_emitted_range` ownership into the funnel (§5 D2a); D9 dormant-
  switch enablement is not this cycle.
- No Nest strategy code is landed.
- Comfort Grace is NOT wired to reclaim in this cycle (former D3 knob-expiry reclaim removed;
  PARKED with data refutation, revival trigger below). Note: the URA-owned reclaim path in C6
  is DISTINCT from the parked D3 (D3 was about reclaiming a HUMAN hold on TAO / immune-person
  expiry; C6 is about reclaiming a URA-OWNED manual — different classification, different
  release channel).

### 0.1 Scope — problems 1, 2, 3, 5 (operator decision 8)

| # | Problem | In-scope? | Deliverable |
|---|---|---|---|
| 1 | After a borrow returns, a manual hold appears at URA's own values and strands (§9.1) | YES | D2.3 provenance last-write record + D2.4 presets-only returns for all sites + D2.3 URA-owned reclaim wiring (binding decision 3) |
| 2 | S1 / arrester write during a live borrow (double-drive) | YES | D2.1 BORROW_LOCK on NUDGE + COMPROMISE only, 10-min hard cap, live-state derivation |
| 3 | Funnel re-issues an already-correct write, causing churn or masking a real intent | YES | D2.5 no-op suppression at funnel + D1 tri-state `WriteResult` |
| 4 | Reclaim on TAO / immune-person expiry (former D3 knob-expiry reclaim) | **REMOVED — PARKED** | Data (2026-08-28 → 2026-09-26): 22 automatic expiries, 0 `preset_change_locked_out` within 3 h; preset changes resume normally. **Revival trigger:** a `preset_change_locked_out` within 3 h of any automatic expiry — file a card `HVAC-KNOB-EXPIRY-RECLAIM-1`. Decision 7 (REV 3) therefore has NO consumer this cycle. **NOTE:** the URA-owned reclaim of binding decision 3 (INV C6) is a SEPARATE reclaim path (URA-owned classification, not human-expiry) and IS in scope under problem 1 / 5. |
| 5 | `_last_emitted_range` doing two jobs (S10/DPM baseline vs funnel no-op suppression); URA-owned reclaim knobs live here (Rung 3 kill switch, Rung 1 delay const) | YES | D2a — split the concept; D4 knobs |
| 6 | Which Carrier feed confirms a URA write took (D2.7 oracle, ship-gate re-issue-rate row) | **REMOVED — separate measurement-only investigation** | Card `HVAC-WRITE-CONFIRMATION-ORACLE-1` (being minted by orchestrator 2026-09-26) to hold the D0 physical-truth probe extension + operator controlled-test. Not blocking. |

### 0.2 CONFIG-FIRST proof (operator decision 12, new standing rule)

Before proposing any code change, enumerate the LIVE knobs that plausibly affect problems 1/2/3/5 and prove no operator setting change alone fixes them. (Values 2026-09-26 eve.)

| Knob | Live value | Site | Problem it could plausibly touch | Why setting it differently does NOT fix the problem |
|---|---|---|---|---|
| `number.ura_hvac_coordinator_ac_nudge_size` | 1.5 °F | `hvac_const.py` (nudge size) | 1, 2 | Smaller nudge does not stop the return write from stranding manual; larger increases wear. |
| `number.ura_hvac_coordinator_ac_nudge_duration` | 2 min | `hvac_const.py` | 1, 2, 3 | Shorter nudge does not fix presets-only-returns or the double-drive during the 2 min window. |
| `number.ura_hvac_coordinator_ac_nudge_eval_delay_seconds` | 240 s | `hvac_const.py` | 3 | Later evaluation cannot prevent the funnel from re-issuing an already-correct write. |
| `number.ura_hvac_coordinator_ac_nudge_daily_backstop` | 40 | `hvac_const.py` | 2 | Fewer nudges reduces exposure but does not fix the double-drive when a nudge IS in flight. |
| `SUPPRESS_TTL_SECONDS` | 15 s (v5.103.17) | `hvac_override.py:133` | 1, 2 | Fixes nudge-start echoes (kind="temp"); does NOT fix the post-restore manual strand (problem 1) or the S1 write during a live borrow (problem 2). |
| `SUPPRESS_TTL_SECONDS_PRESET` | 120 s | `hvac_override.py:173` | — | Blanket suppression, wrong tool for provenance. |
| `number.ura_hvac_coordinator_48_zone_vacancy_delay_minutes` | 10 min | `hvac_const.py:374` | — | Vacancy delay; irrelevant to borrow-return or funnel no-op. |
| `number.ura_hvac_coordinator_zone_entry_dwell` | 0 min (2026-09-26 eve) | `hvac_const.py` | — | Entry dwell; not on the borrow return path. |
| `switch.ura_hvac_coordinator_26_ac_nudge` | on | `switch.py` | 2 | Turning off avoids problem 2 by removing nudges — operator posture is nudges STAY ON. Not a fix. |
| `switch.ura_hvac_coordinator_temp_arrester_override` | off | `switch.py` | — | Only relevant to former problem 4 (parked). |

**Conclusion:** no combination of the above settings closes problems 1/2/3/5. Code change is required.

---

## 1. Institutional context verified

### 1.1 Prior-art scan (Tier 2+ mandate; every proposed piece cited REUSE-or-BUILD)

| Proposed piece | Verdict | Existing at |
|---|---|---|
| `climate.set_preset_mode` funnel + resume-then-pin | REUSE | `hvac_setpoint.py` `emit_set_preset_mode` + `_needs_resume_first` |
| `climate.set_temperature` funnel | REUSE | `hvac_setpoint.py` `emit_set_temperature` |
| `climate.set_hvac_mode` funnel | REUSE (from W1-A) | `hvac_setpoint.py` `emit_set_hvac_mode` (v5.103.16) |
| Durable per-write log with `values_before` / `values_after` / `wire_ok` / `excursion_id` | REUSE (from W1-A) | `ura_activity_log` `climate_write` row (v5.103.16) |
| Excursion primitive `begin_excursion` / `return_excursion` (bookkeeping only) | REUSE — extend, do not replace | `hvac_excursion.py:766` / `:871-1040` |
| Live excursion rows `_rows[zone_id]` (with `kind`, `excursion_id`) | REUSE for BORROW_LOCK derivation | `hvac_excursion.py:798/849` |
| `_nudge_excursion_tokens[zone_id]` (in-flight nudge token) | REUSE for BORROW_LOCK derivation | `hvac_override.py:285/4459-4491/4644` |
| `_nudge_restore_timers[zone_id]` (scheduled restore) | REUSE for BORROW_LOCK derivation | `hvac_override.py` `_restore_after_nudge` scheduler |
| `_corrective_writes_suppressed(zone_id)` (master corrective gate) | REUSE — gates the URA-owned reclaim AND the return-write inside a locked borrow when the human ended it | `hvac_override.py:660-686` |
| Arrester `override_detected` row | REUSE as INPUT (necessary, not sufficient) to the human discriminator | `hvac_override.py:2304-2340` |
| Per-entity `_last_emitted_range` (funnel-suppression + S10/DPM baseline — two jobs) | SPLIT (D2a): funnel keeps its own; S10/DPM moves to `HvacZoneBaseline` | `hvac.py:521` + `hvac_predict.py:889/943/1526` |
| ProvenanceStore (in-memory last-write record per entity, boot-rebuilt from W1-A) | BUILD | new; input is W1-A `climate_write` |
| Per-brand Strategy dispatch memoised by registry `platform` | BUILD (minimal) | HA entity registry |
| **URA-owned reclaim wiring (binding decision 3): reclaim delay Rung-1 const + separate Rung-3 kill switch, invoked on `URA_OWNED_MANUAL` classification when BORROW_LOCK is inactive and `_corrective_writes_suppressed` is False** | **BUILD — reclaim invocation** on top of REUSED gates | writes via `Strategy.hold_preset(entity, s1_current_target)` |
| **Confirmation oracle / `Strategy.confirms()` / D2.7 DATA / bounded retry / `CONFIRMATION_*` consts** | **REMOVED from spec** (moves to separate investigation card `HVAC-WRITE-CONFIRMATION-ORACLE-1`) | — |
| **Knob-expiry reclaim (former D3) / TAO / immune-person / Comfort Grace RECLAIM** | **REMOVED from spec** (PARKED with revival trigger). NB: the URA-owned reclaim above is a DIFFERENT reclaim (URA-owned classification, not human-expiry). | — |

### 1.2 Prior planning docs consulted

- `docs/planning/PLANNING_hvac_governed_excursion.md` — rev-6 banner (lease gate stripped; do not rebuild). `return_excursion` is bookkeeping-only.
- `docs/planning/PLANNING_hvac_excursion_restore_unified.md` — parked D2/D3/D4 rework (3 CRITICALs from 2026-08-26). REV 4 respects the parking: does not rebuild the D2 AST gate, D3 recovery interlock, or the S14 off-phase-ceiling token.
- `docs/planning/PLANNING_hvac_live_room_establishment.md` — Stage 0 SHIPPED v5.103.15.
- `docs/planning/AUDIT_thermostat_write_paths_2026_09_16` — `set_preset_mode` 10/10 funnelled; `set_temperature` 11/11 funnelled; `set_hvac_mode` 7/7 funnelled (W1-A Stage A).
- REV 3 of this file — superseded by REV 4 (git history preserved).

### 1.3 Memory bodies pulled

`feedback_extend_existing_never_rebuild`, `feedback_wire_in_anchor_mandatory`, `feedback_suppression_needs_discharge` (borrow-lock discharge = 10-min hard cap + human-ends-borrow), `feedback_mutation_verification_pycache_staleness`, `feedback_no_soak`, `feedback_do_robust_fix_not_bandaid_and_card`, `feedback_tier2plus_prior_art_scan`, `feedback_falsify_before_asserting`, `feedback_hollow_test_anchors` (grep is not a test — Bug Class #62; the D2.6 completeness anchor MUST be behavioural + AST-lint, not a source grep), `feedback_coincidental_equality_masks_concept_split`, `feedback_measure_before_build` (D0 gates on ≥ 2 days post-v5.103.17), `feedback_marginal_benefit_pushback` (justifies the scope cut).

### 1.4 REV-3 plan reviews — findings folded (survivors only, post scope cut) + orchestrator re-review

| Reviewer / finding | Verdict in REV 4 | Where |
|---|---|---|
| Reviewer #1 CRIT-2 — `override_detected` alone is not a human discriminator | FOLDED | §5 D2.3 explicit discriminator |
| Reviewer #2 CRIT-2 — same, restated in classifier | FOLDED | §5 D2.3 / D2.6 |
| Reviewer #2 CRIT-3 — corrected inventory of ALL real return paths (11 sites). Verify every line on current `develop` before edit. | FOLDED | §5 D2.4 verified inventory (line refresh in build) |
| Reviewer #2 CRIT-4 — lock built from `_override_active` was WRONG; must build from `_rows[zone_id]` (kind ∈ NUDGE/COMPROMISE) + `_nudge_excursion_tokens` + `_nudge_restore_timers`; borrow's own return exempted by `excursion_id` match | FOLDED | §5 D2.1 |
| Reviewer #1 CRIT-3 — write funnels need tri-state result | FOLDED | §5 D1 `WriteResult` tri-state |
| Reviewer #1 HIGH — 28-site table (site × verb × Strategy method or direct-funnel-with-reason × gates), incl. `heat_cool` enforcer + every borrow start | FOLDED | §5 D2.8 |
| Reviewer #2 HIGH — D1 truly behaviour-neutral; say WHERE resume-then-pin lives; exempt W1-A `_snapshot_climate_state` | FOLDED | §5 D1 explicit note |
| Reviewer #1 MED — D5 generic default fully specified | FOLDED | §5 D5 (kept from REV 3 minus oracle-trivial branch) |
| Reviewer #2 MED — refresh line citations against current `develop` | FOLDED | citations refreshed inline; build re-verifies |
| Reviewer #1 MED — `zone.preset_mode` "status says X" reads routed through `Strategy.classify` | FOLDED | §5 D2.6 |
| Reviewer #1 LOW — retry / no-op limited to what problems 1/3 need (no confirmation oracle) | FOLDED | §5 D2.5 |
| REV 3 D2.7 oracle + `CONFIRMATION_*` consts + bounded retry + `[CONFIRMATION EXHAUSTED]` NM | **DROPPED** (moved to separate measurement-only investigation card `HVAC-WRITE-CONFIRMATION-ORACLE-1`) | §0.1, §2, §4 |
| REV 3 former D3 knob-expiry reclaim + Comfort Grace REMOVAL from that reclaim | **DROPPED / PARKED** | §0.1 (revival trigger) |
| **ORCHESTRATOR RE-REVIEW #1 (2026-09-26 evening)** — the first REV 4 draft ALSO removed binding decision 3's URA-owned reclaim delay + kill switch "with D3." Wrong: decision 8 removed the knob-expiry reclaim (problem 4) only; decision 3 governs the URA-owned reclaim (problem 1 / 5) which is IN SCOPE. **RESTORED.** | FOLDED | §5 D2.3 URA-owned reclaim path; §5 D4 (1-tick delay + kill switch); §0 INV C6; §7 ship gate C6 |
| **ORCHESTRATOR RE-REVIEW #2** — "C3-style grep test" for raw `preset_mode` reads is a source grep, not a test (Bug Class #62, banned). Replace with a behavioural per-site anchor (drive each trust reader with a `Strategy.classify` that disagrees with the raw attribute; assert the decision follows classify) + AST-based completeness lint on Attribute/Subscript access to `preset_mode`, following W1-A's `test_hvac_climate_write_funnel_completeness.py` pattern, with an allowlist of display-only sites carrying reasons. | FOLDED | §5 D2.6 rewritten |
| **ORCHESTRATOR RE-REVIEW #3** — `HVAC-WRITE-CONFIRMATION-ORACLE-1` was not previously on the board; the orchestrator is creating it now. Keep the reference. | FOLDED | §0.1 problem-6 row + §1.1 REMOVED row + §2 non-goals + §9 sequencing note |

### 1.5 Design docs read

- `docs/Coordinator/HVAC_ARCHITECTURE_STATE_OF_PLAY.md` — full read (mandatory); §6, §7, §9.1, §9.7, and §10 C17 / C20-C24 folded.
- `docs/Coordinator/THERMOSTAT_DEFINITION_CARRIER_BRYANT.md` rev 2 — companion, still current for §5 D2.4 sequencing.
- `docs/readmes/README_v5.103.16.md` — W1-A ledger row shape (input to ProvenanceStore).
- `docs/readmes/README_v5.103.17.md` — `SUPPRESS_TTL_SECONDS` 5 → 15 s, kind="temp" only; residuals under kind="preset" and > 15 s under kind="temp" are exactly the surface D2.3 handles.

### 1.6 Code locations surveyed end-to-end (with refreshed citations)

- `custom_components/universal_room_automation/domain_coordinators/hvac_setpoint.py` — `emit_set_temperature`, `emit_set_preset_mode`, `emit_set_hvac_mode`, `_needs_resume_first`.
- `.../hvac_excursion.py` — `_rows` `:798/849`, kinds `:94-104`, `_auto_return` `:667`, boot NUDGE restore `:1131`, `auto_release_on_incomplete` `:1322`, `return_excursion` bookkeeping `:871-1040` (docstring `:886-888`).
- `.../hvac_override.py` — `SUPPRESS_TTL_SECONDS = 15` `:133`, `SUPPRESS_TTL_SECONDS_PRESET = 120` `:173`, `_nudge_excursion_tokens` `:285/4459-4491/4644`, `_corrective_writes_suppressed` `:660-686`, `override_detected` `:2304-2340`, arrester compromise `:3393`, arrester revert `:3519/3547`, hard reset `:3888/4006/4041/4113`, nudge start `:4423`, nudge restore setpoint `:4595/S6`, nudge restore preset `:4640/S7` (incl. corrective-gate exception `:4622-4640`, `:4674-4685`), S8 cancel `:5814/5841`, S9 boot audit `:6220-6245`.
- `.../hvac.py` — S1 dispatch `:2674`, ledger `:2716-2748`, lockout `:2504-2539`, `heat_cool` enforcer `:1926-1938`, `_last_emitted_range` `:521`, S10 DPM `:3046`, ledger fields `:429/3023/3068`.
- `.../hvac_predict.py` — S11 banking `:979/1040`, S12 pre-cool `:1160`, S13 pre-heat `:1448/1511/1560`, DPM baseline `:889/943/1526`.
- `.../hvac_egress.py` — pause `:683`, resume `:779/795`.
- `.../hvac_preset.py:202-217` — `should_change_preset`.
- W1-A completeness lint precedent: `quality/tests/domain_coordinators/test_hvac_climate_write_funnel_completeness.py` (the AST-based pattern D2.6's completeness lint follows).

**Line-refresh discipline.** Every file:line in §5 will be re-verified in the first commit of the build against `develop` at build-start; any drift is fixed in that same commit before D2 code lands.

---

## 2. Non-goals (explicit)

- No confirmation oracle / `Strategy.confirms()` / D2.7 DATA / bounded retry / `CONFIRMATION_*` constants. (Separate investigation card `HVAC-WRITE-CONFIRMATION-ORACLE-1`, being minted by the orchestrator 2026-09-26.)
- No knob-expiry reclaim (former D3), no Comfort Grace RECLAIM changes, no Temp-Arrester-Override / immune-person expiry reclaim wiring. (PARKED, revival trigger in §0.1.) The URA-owned reclaim of binding decision 3 (INV C6) is a DIFFERENT reclaim and IS in scope.
- No coherence classifier (`URA_ECHO_MANUAL` withdrawn per C20).
- No profile-setpoint match classifier.
- No universal cross-brand "which feed is authoritative" rule.
- No Nest strategy code.
- No `set_activity_setpoint` adoption for nudges this cycle (former Q1).
- No schedule-boundary guard against the vendor resume race (former Q2 — operator reduces schedules).
- No enablement of D9 / F2 / F4 (Custom Preset Ranges); this cycle only unblocks by splitting `_last_emitted_range` (§5 D2a).
- No `hvac_activity_log` writer-attribution across integrations.
- No grep-only "no raw `preset_mode` reads" test. (Bug Class #62 — a source grep is not a test. §5 D2.6 uses behavioural per-site anchors + an AST completeness lint instead.)

---

## 3. D0 — Read-only measurement gate (MANDATORY, BLOCKS design freeze; gated on v5.103.17 shipping)

Per Measure-Before-Build: the strand-window sizing is the single empirical dependency the build has. It CAN be scoped now (this plan is buildable), but **D2 fixture thresholds are confirmed by D0 over ≥ 2 days of post-v5.103.17 data before the build's D2 merges.**

**Data sources** (all already exist):
- URA DB: `ac_ramp_events` (`nudge_started`, `nudge_restored`, `nudge_settled`), `hvac_excursion_events`, `ura_activity_log` (`preset_change`, `preset_change_locked_out`, `override_detected`, comfort rows).
- W1-A `climate_write` durable log (v5.103.16) — `values_before` incl. `preset_mode` AND `hold_activity`, `values_after`, `wire_ok`, `excursion_id`, `site`, `zone_id`, `reason`, `ts_issued` / `ts_returned`.
- HA recorder `home-assistant_v2.db` for `preset_mode`, `hold_activity`, `temperature`, `target_temp_high/low`, `hvac_mode` on the three Carrier zones.

**D0 outputs (drive §5 D2 fixture table):**

1. **Per-episode strand extraction** for every borrow return in the window (nudge + non-nudge): verbs in return, order, times, values; hold_activity at pin time; time from `nudge_restored` until a `manual` observation on `hold_activity`; whether any refresh-triggering event landed between; sibling-zone writes on the same account.
2. **Post-restore strand-window sizing.** The echo-fix Review B measured residual strands ~300-370 s post `nudge_restored`. D0 confirms this window against ≥ 2 days of post-v5.103.17 data and outputs a `STRAND_WINDOW_S` value that seats the ProvenanceStore's URA-ownership window (§5 D2.3), the "no fresh return write on human-ended borrow" observation window (§5 D2.1 C3), and the ship-gate falsifier window (§7).
3. **Config-combination matrix** built passively: for each combination of (verb order, hold state at pin, sibling activity, refresh coincidence), count strand vs no-strand. Each combination becomes a named fixture in D2.
4. **Human-discriminator calibration.** For every `override_detected` row in the window whose `values_before.preset_mode == "manual"`: is there a preceding URA `climate_write` on the entity within `URA_OWNED_TOLERANCE_F = 0.5` in the last 15 s? If yes, mark it as a URA echo (must NOT count as human under §5 D2.3). If no, mark it as a candidate genuine human. This population sizes the discriminator's false-positive / false-negative rate BEFORE the build ships.

**Discrimination:**
- If bare pin over anonymous hold in strand cases → §5 D2.4 presets-only-returns is the fix.
- If shared-account guard wipe (C16) dominates → §5 D2.3 provenance reclaim (INV C6) is the operative fix (URA cannot defend the pin, but can reclaim the manual it caused).
- If both → both fixes needed (still inside §5 D2 scope).
- If neither → return to the operator; the mechanism is unenumerated.

**Non-negotiable:** the build MAY start on D1 + D4 + D5 immediately (they do not depend on D0), but D2 fixture table (and therefore D2.3 constants and D2.4 acceptance) is not FROZEN until D0 completes.

Output artefact: `docs/planning/AUDIT_hvac_w1b_strand_mechanism_2026_09_XX.md`.

---

## 4. Deliverable order (REV 4)

1. **D0** — read-only measurement (§3); gates on ≥ 2 days of post-v5.103.17 data.
2. **D1** — generic strategy interface, truly behaviour-neutral, tri-state `WriteResult` (§5 D1).
3. **D4** — module constants + Rung-3 kill switch entity for URA-owned reclaim (§5 D4).
4. **D5** — fully specified generic default (§5 D5).
5. **D2** — Carrier strategy: BORROW_LOCK (D2.1), ProvenanceStore + human discriminator + URA-owned reclaim invocation (D2.3), presets-only returns per-site migration (D2.4), no-op suppression at funnel (D2.5), S1 + arrester + consumer wiring + behavioural anchors + AST completeness lint (D2.6), 28-site table enforcement (D2.8), split `_last_emitted_range` (D2a).
6. **Live-validation write-back** into `README_v<version>.md`.

(No former D3 knob-expiry reclaim — parked per §0.1. The URA-owned reclaim of binding decision 3 lives in D2.3 + D4. No D6 — folded into D2 per REV 3 finding #16, each per-site edit replaces the site's inline pair in the SAME edit.)

---

## 5. Deliverables

### D1 — Generic strategy interface (truly behaviour-neutral)

A stateless module `domain_coordinators/hvac_strategy.py`:

```
strategy_for(hass, entity_id) -> Strategy   # cached per BRAND (by registry.platform); never cache fallback
Strategy.observe(hass, entity_id) -> HoldObservation
Strategy.classify(observation, provenance) -> HoldClassification
Strategy.hold_preset(hass, entity_id, preset, *, gate=None, blocking=False, zone_id, reason, site) -> WriteResult
Strategy.borrow(hass, entity_id, kind, *, gate, duration, freeze, snapshot, zone_id, reason, site) -> WriteResult
Strategy.return_borrow(hass, entity_id, snapshot, *, gate=None, zone_id, reason, site) -> WriteResult
```

`WriteResult = (status: {APPLIED, SKIPPED_ALREADY_CORRECT, FAILED}, reason: str, exc: Optional[str])`. This is the tri-state Reviewer #1 CRIT-3 asked for. Every funnel call site inspects `.status`:
- `APPLIED` — proceed as today.
- `SKIPPED_ALREADY_CORRECT` — do not emit ledger `preset_change_locked_out`; log at DEBUG only.
- `FAILED` — surface via existing NM latch path for return sites; retry semantics limited to what problem 1 needs (one retry on a return, with discharge — no bounded retry against unconfirmed observations; there is no confirmation oracle).

`HoldObservation = {preset_mode, hold_activity, target_high, target_low, hvac_mode, read_at, observed_at_source: 'live_state'}`. Carrier vocabulary (`resume`, `manual`, `hold_activity`) MUST NOT leak past `CarrierStrategy` boundaries.

`HoldClassification ∈ {NAMED_HOLD, URA_OWNED_MANUAL, HUMAN_MANUAL, NO_HOLD}` — no `URA_ECHO_MANUAL`, no profile-match.

**D1 ships truly behaviour-neutral:**
- Every method body is TODAY'S funnel behaviour behind the Strategy indirection.
- **Resume-then-pin stays where it lives today** — inside `emit_set_preset_mode` / `_needs_resume_first` in `hvac_setpoint.py`. D1 does not move that logic; `CarrierStrategy.hold_preset` calls into the existing funnel. Byte-identity preserved for the pre-D2 name-diff.
- **W1-A `_snapshot_climate_state`** (the synchronous pre-write attribute read that populates `climate_write.values_before`) is EXEMPT from Strategy dispatch — it reads raw attributes by design and must stay behind the funnel where W1-A put it. D1 wires an explicit exemption comment at the read site.

**Dispatch rule.** Look up entity in HA entity registry, read `RegistryEntry.platform`, cache per platform. Registry miss → generic default for THIS call, NOT cached.

**Acceptance:**
- `test_strategy_dispatch_by_registry_platform` — Carrier → CarrierStrategy; fake platform → generic default. Discriminating: fake platform's `hold_preset` MUST NOT emit `resume` even when `hold_activity == "manual"`.
- `test_strategy_cache_by_brand` — two Carrier entities share ONE instance; registry miss on a Carrier entity returns the generic default WITHOUT polluting the cache.
- `test_write_result_tristate_reports_skipped_when_no_op` — a funnel call whose intended values match the last-sent record AND the observation returns `SKIPPED_ALREADY_CORRECT`; ZERO service calls.
- `test_d1_behaviour_neutral_suite_name_diff` — full suite run pre-D2 shows a clean name-diff vs pre-D1 baseline.
- Live: post-restart, grep confirms every `climate.set_*` call sits inside a funnel; every W1-A `climate_write` row still lands.

### D2 — Carrier strategy (load-bearing)

Every site listed in the D2.4 verified inventory is migrated in the SAME edit that removes its inline `(setpoints → preset)` return pair.

#### D2.1 BORROW_LOCK (operator decision 9) — nudges + compromises only, 10 min hard cap

Derive `BORROW_LOCK(entity_id) → (armed: bool, live_token: Optional[Token], armed_since: ts)` from LIVE runtime state (NOT `_override_active`, NOT any non-existent `hvac_excursion_state` column):

```
armed = (
    any(row.kind in {NUDGE, COMPROMISE} for row in hvac_excursion._rows.values()
        if row.entity_id == entity_id)                  # hvac_excursion.py:798/849
    OR hvac_override._nudge_excursion_tokens.get(zone_id) is not None   # hvac_override.py:285
    OR zone_id in hvac_override._nudge_restore_timers    # scheduled restore in flight
)
live_token = the token backing whichever of the three fired
```

Banking, pre-cool, pre-heat, egress are **NEVER** in this set (long by design; the rev-6 lease gate strip is exactly why).

**Gate at:**
- S1 preset dispatch (`hvac.py:2674`): while `BORROW_LOCK(entity).armed` AND caller is NOT carrying `live_token.excursion_id`, S1 emits nothing to that entity and logs a `preset_write_borrow_locked` row (NOT `preset_change_locked_out`).
- Arrester override detection (`hvac_override.py:2304-2340`): while armed, no override booking and no revert against this entity.
- **URA-owned reclaim path (§5 D2.3):** BORROW_LOCK gates it (does not fire while armed).
- Return-write path (the borrow's OWN return): EXEMPT — the return writes MUST carry `excursion_id == live_token.excursion_id` (already true today via `_nudge_excursion_tokens[zone_id].excursion_id`, `hvac_override.py:4644`).

**Hard cap (bounded discharge — required by `feedback_suppression_needs_discharge`).** `BORROW_LOCK_HARD_CAP_S = 600` (10 min; rung-1 module const). Measured live durations that fit under the cap: nudges 2 min (`number.ura_hvac_coordinator_ac_nudge_duration`), compromises 5.0-6.4 min, banking/pre-cool exactly 120 min (banking/pre-cool NOT locked, so cap does not apply). On cap:
- Lock ENDS for that entity.
- Normal writers resume on that entity's next tick.
- One NM `[BORROW LOCK CAP HIT]` per entity per lock-arming (dedup by `(entity_id, armed_since)`).
- The still-open excursion row is LEFT open for sweep pickup via the existing `auto_release_on_incomplete` path (`hvac_excursion.py:1322`, unchanged).

**Human ends locked borrow (operator decision 10, INV C3):**
- Detection is echo-safe (§5 D2.3 discriminator; after the 15 s temp-kind window).
- On detection while armed: lock ENDS, excursion row is CLOSED with outcome `human_ended_no_restore`, NO return write fires. The arrester picks it up as an ordinary override on the next tick.
- Specifically, today's nudge restore in `hvac_override.py:4617-4700+` (with the deliberate `_corrective_writes_suppressed` exception at `:4622-4640` and the unconditional preset write at `:4674-4685`) is MODIFIED for the locked kinds: `_restore_after_nudge` FIRST calls `Strategy.classify(observe(), provenance)`; if the classification is `HUMAN_MANUAL` inside the borrow-lock window, the method returns without emitting `emit_set_temperature` or `emit_set_preset_mode`, closes the excursion with `human_ended_no_restore`, and clears `_nudge_excursion_tokens[zone_id]` / `_nudge_pre_preset[zone_id]`. If the classification is anything else, the existing restore runs unchanged.

**Per-kind falsifier tests.** For each of NUDGE and COMPROMISE:
1. Start the kind; assert `BORROW_LOCK(entity).armed` is True at that entity.
2. Mutate the source that populates the specific state (`_rows[zone_id]` for compromise, `_nudge_excursion_tokens` for nudge): each mutation MUST produce a SPECIFIC named test failure.
3. Time-travel past `BORROW_LOCK_HARD_CAP_S`: lock releases, NM emitted, writers resume.
4. Inject a `HUMAN_MANUAL` classification inside the lock window: return method returns without any funnel call; excursion closes `human_ended_no_restore`.
5. Assert the borrow's OWN return with matching `excursion_id` is NOT gated.

#### D2.3 ProvenanceStore + human discriminator + URA-owned reclaim (operator decision 11b + binding decision 3)

New in-memory helper module `hvac_provenance.py`:

```
ProvenanceStore.record(entity_id, verb, values_after, wrote_at, values_before, source_site)
ProvenanceStore.last_write_for(entity_id) -> Optional[WriteRecord]
ProvenanceStore.classify(entity_id, observation) -> HoldClassification
ProvenanceStore.detect_human_change(entity_id, since_ts) -> Optional[HumanChangeEvidence]
ProvenanceStore.clear(entity_id)              # every actual write resets prior record for entity
ProvenanceStore.rebuild_on_boot(hass)         # from hvac_excursion_state + LAST climate_write row
```

**`values_after` semantics (operator decision 11b, "APPLIED values post freeze-floor / deadband").** The record captures what the FUNNEL actually asked the wire to send, AFTER any freeze-floor and deadband transforms. W1-A's `climate_write.values_after` is exactly this. Boot rebuild reads it verbatim. `wrote_at = climate_write.ts_returned` (`ts_issued` also captured for diagnostics).

**URA-ownership rule (INV C4).** For an observation with `preset_mode == "manual"` on `entity_id`:
- Let `rec = last_write_for(entity_id)`.
- If `rec is None` OR `rec.wrote_at` is older than `STRAND_WINDOW_S` (D0-sized, seed 400 s pending D0 confirmation): classify `HUMAN_MANUAL`.
- If `abs(observation.target_high - rec.values_after.target_high) <= URA_OWNED_TOLERANCE_F` AND same for `target_low` (tolerance 0.5 °F — device displays whole degrees) AND `observation.hold_activity` transitioned to `manual` AT OR AFTER `rec.wrote_at` AND `detect_human_change(entity_id, since_ts=rec.wrote_at)` returns None: classify `URA_OWNED_MANUAL`.
- Else: classify `HUMAN_MANUAL`.

**Human discriminator (operator decision 10 / 11b — MUST NOT rely on `override_detected` alone; echo-safe).** `detect_human_change(entity_id, since_ts) -> Optional[HumanChangeEvidence]` returns non-None IFF ALL of:
1. There is an `override_detected` row (`hvac_override.py:2304-2340`) on `entity_id` with `ts >= since_ts + SUPPRESS_TTL_SECONDS` (OUTSIDE the 15 s temp-kind echo window; D2.3 re-applies the window so a future change to `SUPPRESS_TTL_SECONDS` cannot silently loosen the discriminator).
2. That row's `values_before` do NOT match any W1-A `climate_write.values_after` on the same entity within `[ts - SUPPRESS_TTL_SECONDS, ts]` at tolerance `URA_OWNED_TOLERANCE_F` (excludes echoes of URA's own writes).
3. Setpoint delta from URA's `last_write_for(entity).values_after` at time of the observed `override_detected` is EITHER (a) ≥ `URA_OWNED_TOLERANCE_F` (a real value change), OR (b) accompanied by an interactive hint (`preset_mode` moved to something other than the Carrier "manual" alias — e.g. a named preset the user picked in the Carrier app; captured via observation delta).

Rationale: `override_detected` alone is necessary but NOT sufficient — Reviewer #1 CRIT-2 and Reviewer #2 CRIT-2. Calibration is a D0 output.

**Boot rebuild.** Load the LAST `climate_write` row per entity (verb, `values_after`, `ts_returned`, `values_before`, `source_site`, `excursion_id`) from `ura_activity_log`. If the last row is within `STRAND_WINDOW_S` of boot, record it as active provenance; older records expire on read. Empty store on boot → classification errs to `HUMAN_MANUAL` (safe direction); NM one-shot `[PROVENANCE STORE EMPTY ON BOOT]`.

**Read API (operator decision 11b).**
```
ProvenanceStore.last_write_for(entity_id) -> Optional[WriteRecord]
    # WriteRecord = (verb, values_after, values_before, wrote_at, source_site, excursion_id)
ProvenanceStore.is_ura_owned_manual(entity_id, observation) -> bool
```

Consumers: `hvac_preset.should_change_preset` (D2.6 wiring), `CarrierStrategy.classify` (D1 dispatch), diagnostic sensor `sensor.ura_hvac_coordinator_zone_<n>_last_ura_write_at`.

##### D2.3-R — URA-owned reclaim wiring (binding decision 3, RESTORED per orchestrator re-review, INV C6)

Binding decision 3 (2026-09-26, verbatim in the Operator decisions section below): *"Reclaim DELAY for a URA-owned manual hold with no live borrow = 1 tick (same-tick eligible), plus a separate kill switch."*

This is the reclaim path for problem 1 / 5 — DISTINCT from the parked former D3 (knob-expiry reclaim of a HUMAN hold on TAO / immune-person expiry).

**Trigger.** On any decision cycle, for each zone:
1. `obs = Strategy.observe(entity)`; `cls = Strategy.classify(obs, provenance)`.
2. If `cls != URA_OWNED_MANUAL`: skip (S1's existing lockout / named-hold paths handle it).
3. If `BORROW_LOCK(entity).armed`: skip (a borrow is live; the return will restore).
4. If `_corrective_writes_suppressed(zone_id)` (Temp Arrester Override active OR immune-hold on the zone, `hvac_override.py:660-686`): skip.
5. If `switch.ura_hvac_coordinator_ura_owned_manual_reclaim_enabled` is OFF (§5 D4): skip (S1 behaves as today; the lockout is the operator's observable "off" state).
6. Compute `age_since_classification = now - classification_first_seen_ts`. If `age_since_classification < URA_OWNED_RECLAIM_DELAY_S` (default 0 s = same-tick): skip this tick; the NEXT tick will re-classify and either fire or skip.
7. Otherwise: `Strategy.hold_preset(entity, s1_current_target_preset, site="S1_ura_owned_reclaim", zone_id=zone_id, reason="ura_owned_manual_reclaim", blocking=False)`. Result handled per D1 tri-state.

**`classification_first_seen_ts`.** Recorded on the transition from any other classification to `URA_OWNED_MANUAL` for `entity_id`; cleared on any transition away. Held in the ProvenanceStore. Restart: an in-memory value, re-seeded from the current classification on the first post-boot tick.

**Kill switch semantics (Rung 3 Switch entity — see §5 D4).**
- ON (default): reclaim fires per steps 1-7 above.
- OFF: reclaim never fires, regardless of `URA_OWNED_RECLAIM_DELAY_S`. S1 sees the `URA_OWNED_MANUAL` classification and behaves per today's `should_change_preset` refusal path — but the classification itself is still visible in diagnostics (so the operator sees WHY nothing happened). Distinguishes "off" from "very delayed."
- The switch is a `SwitchEntity` with `RestoreEntity` persistence, exposed via the standard URA switch platform (`switch.py`).

**BORROW_ACTIVE / corrective-writes / no-op interactions.** The reclaim write goes through the SAME funnel as any other preset write, so D2.5 no-op suppression applies (if S1's current target already matches the observed preset — which it won't in a strand, but might on race — the reclaim is `SKIPPED_ALREADY_CORRECT` with no service call).

**Acceptance:**
- `test_ura_owned_reclaim_fires_same_tick_at_default_delay` — classification `URA_OWNED_MANUAL`, no borrow, kill switch ON, delay = 0: exactly ONE `hold_preset(s1_current_target)` fires on the same tick.
- `test_ura_owned_reclaim_honours_delay_120s` — same setup, delay = 120 s: reclaim fires on the SECOND tick after classification (delay > 1 tick). Discriminating: contrast with delay = 0.
- `test_ura_owned_reclaim_kill_switch_off_no_write_no_lockout_change` — kill switch OFF: NO reclaim write; S1's existing lockout behaviour on `URA_OWNED_MANUAL` classification is UNCHANGED (equivalent to REV 4's C4 non-lockout policy, i.e. S1 does NOT lockout on URA_OWNED_MANUAL; the kill switch OFF disables the RECLAIM but keeps the classification honesty). Discriminating: contrast with kill switch ON — one write fires, kill switch OFF — zero writes fire.
- `test_ura_owned_reclaim_gated_by_borrow_active` — while BORROW_LOCK armed on the entity: no reclaim fires even if URA_OWNED_MANUAL is classified. Discriminating: end the borrow; the reclaim then fires.
- `test_ura_owned_reclaim_gated_by_corrective_writes_suppressed` — TAO active on the zone: no reclaim fires. Discriminating: clear TAO; reclaim fires.
- `test_ura_owned_reclaim_restart_seeds_classification_ts` — restart with a URA-owned manual pre-existing: `classification_first_seen_ts` re-seeded on first post-boot tick; reclaim fires on the tick where age exceeds delay.
- **Live:** post-restart, the four historical strand cases in §9.1 replay against the strategy as fixtures and clear within one tick after classification (kill switch ON).

#### D2.4 Presets-only returns per verified inventory (operator decision 11a)

**Verified inventory (Reviewer #2 CRIT-3, re-verified against `develop` at build-start — do NOT copy citations from this doc, verify).**

| # | Site | File:line (as of REV 4) | Kind | Return contract |
|---|---|---|---|---|
| 1 | `_auto_return` (lease-expiry) | `hvac_excursion.py:667` | NUDGE-excluded | presets-only if snapshot named; setpoints+preset only if snapshot is `HUMAN_MANUAL` |
| 2 | Boot NUDGE restore | `hvac_excursion.py:1131` | NUDGE (boot) | presets-only |
| 3 | S4 arrester revert (setpoints) | `hvac_override.py:3531` | COMPROMISE | presets-only |
| 4 | S4 arrester revert (preset) | `hvac_override.py:3561` | COMPROMISE | same edit as #3 |
| 5 | Hard reset restore #1 | `hvac_override.py:4028` | HARD_RESET | presets-only |
| 6 | Hard reset restore #2 | `hvac_override.py:4067` | HARD_RESET | presets-only |
| 7 | Hard reset restore #3 | `hvac_override.py:4142` | HARD_RESET | presets-only |
| 8 | S6 nudge restore setpoint | `hvac_override.py:4633` | NUDGE | presets-only (drops the setpoint write in the migrated edit; D2.1 humans-end-borrow guard added at method entry) |
| 9 | S7 nudge restore preset | `hvac_override.py:4681` | NUDGE | presets-only (this is the preset call that remains) |
| 10 | S8 cancel-nudge setpoint | `hvac_override.py:5860` | NUDGE (button) | presets-only |
| 11 | S8 cancel-nudge preset | `hvac_override.py:5889` | NUDGE (button) | same edit as #10 |
| 12 | S9 boot audit setpoint | `hvac_override.py:6272` | NUDGE (boot audit) | presets-only |
| 13 | S9 boot audit preset | `hvac_override.py:6296` | NUDGE (boot audit) | same edit as #12 |
| 14 | S11 banking release setpoint | `hvac_predict.py:984` | BANKING | presets-only |
| 15 | S11 banking release preset | `hvac_predict.py:1046` | BANKING | same edit as #14 |
| 16 | S13 pre-heat release setpoint | `hvac_predict.py:1520` | PRE-HEAT | presets-only |
| 17 | S13 pre-heat release preset | `hvac_predict.py:1570` | PRE-HEAT | same edit as #16 |
| 18 | Egress resume setpoint | `hvac_egress.py:794` | EGRESS_PAUSE | presets-only |
| 19 | Egress resume preset | `hvac_egress.py:815` | EGRESS_PAUSE | same edit as #18 |
| — | `auto_release_on_incomplete` | `hvac_excursion.py:1322` | any | **STAYS no-write** (verified; do not add a write here) |

**Return contract per site:**
1. Compute via `Strategy.return_borrow(entity_id, snapshot, ...)`.
2. Order: **mode → preset → (setpoints only if strategy says no presets available OR snapshot is HUMAN_MANUAL)**.
3. Named-preset snapshot → presets-only path.
4. `HUMAN_MANUAL` snapshot → setpoints+preset fallback with the human's values (INV carve-out).
5. On `WriteResult.status == FAILED`: one retry with discharge (delay), pass through the site's `gate`; on second failure emit `[GOVERNED BORROW RESTORE FAILED]` NM latch, leave excursion row open for sweep pickup.
6. Site still calls `return_excursion` for bookkeeping.

**Per-site service-call-count test (Reviewer C).** For each of the 19 sites, drive the return path with a named-preset snapshot and assert exactly ONE `set_preset_mode`, ZERO `set_temperature`, ZERO redundant `resume` unless `hold_activity == "manual"` at pin time. For a `HUMAN_MANUAL` snapshot: ONE `set_temperature`, ONE `set_preset_mode`. Discriminating: swap the snapshot classifier's verdict; counts must flip.

**Per-site source-mutation test.** For each site, edit the production source at that site to bypass the Strategy call; a SPECIFIC named test MUST fail; restore.

#### D2.5 No-op write suppression at the funnel (problem 3)

Suppress iff BOTH:
- (a) intended `(verb, values)` equal the funnel's last-sent record for this entity, AND
- (b) the observed state equals those values (within `URA_OWNED_TOLERANCE_F` on setpoints).

On suppression: return `WriteResult(status=SKIPPED_ALREADY_CORRECT, reason='no_op_last_sent_matches')`; ZERO service calls; ZERO `preset_change_locked_out` row.

**Explicit non-goals (Reviewer #1 LOW folded):**
- No `Strategy.confirms()` oracle. No `CONFIRMATION_*` constants / bounded retry / `[CONFIRMATION EXHAUSTED]` NM latch.
- The no-op suppression does not attempt to reason about STATUS↔CONFIG feed disagreement (§9.7); that is `HVAC-WRITE-CONFIRMATION-ORACLE-1`'s problem.

Any actual write to the entity clears every verb's last-sent record. Observed divergence clears the record. Return-write path (D2.4) inspects `WriteResult.status`; if `SKIPPED_ALREADY_CORRECT` on the preset pin, the return is CLEAN — no retry, no NM. The URA-owned reclaim (D2.3-R) is also subject to no-op suppression — a reclaim that would re-issue an already-correct preset is skipped.

**Restart:** in-memory record; boot-rebuilt from the LAST `climate_write` row per entity (same source as ProvenanceStore).

#### D2.6 S1 + arrester + consumer wiring — behavioural anchors + AST completeness lint (orchestrator re-review, Bug Class #62)

**S1 wiring:**
- `should_change_preset` (`hvac_preset.py:212-217`) reads `Strategy.classify(observe(), provenance)`.
- Refusal branch fires only on `HUMAN_MANUAL`. `URA_OWNED_MANUAL` returns "OK to change" (subject to `BORROW_LOCK` and `_corrective_writes_suppressed`); the D2.3-R reclaim path is what actually writes.
- Lockout ledger row (`hvac.py:2504-2539`) writes only for `HUMAN_MANUAL` refusals; borrow-locked skips write `preset_write_borrow_locked` instead.

**Every reader of `preset_mode` for TRUST (not display) routes through `Strategy.classify(observe(), provenance)`** (Reviewer #1 MED). Completeness is enforced by TWO mechanisms — **not a source grep** (source grep is not a test — Bug Class #62, banned by `feedback_hollow_test_anchors`):

**(a) Behavioural per-site anchor.** For every trust reader listed in the consumer table below, write ONE behavioural test that:
1. Sets up a Strategy fixture whose `classify()` DISAGREES with the raw `preset_mode` attribute — e.g. raw attribute reads `manual` but Strategy classifies `URA_OWNED_MANUAL`, or raw reads `home` but Strategy classifies `HUMAN_MANUAL` (via a NAMED_HOLD variant if the site permits).
2. Drives the reader (calls the enclosing method with realistic inputs).
3. Asserts the decision the reader emits FOLLOWS the Strategy classification, not the raw attribute. Discriminating: swap the Strategy fixture's verdict, assert the decision flips.
4. Reviewer C mutation: bypass the Strategy call at the reader's site (patch the source line to read the raw attribute); the test MUST go RED with a specific named failure.

**(b) AST-based completeness lint** — new test `test_hvac_preset_mode_read_completeness.py`, following the W1-A precedent `quality/tests/domain_coordinators/test_hvac_climate_write_funnel_completeness.py`. Walks the AST of every module under `custom_components/universal_room_automation/domain_coordinators/hvac*.py`, flags every `Attribute` or `Subscript` access of the form `<expr>.attributes["preset_mode"]`, `<expr>.attributes.get("preset_mode"[, ...])`, `<state>.attributes["preset_mode"]`, and any `state.preset_mode` on a `climate` state object, then compares against an allowlist. The allowlist is a Python dict `{module_relative_path: {line_number_or_symbol: reason}}` maintained in the test file itself; the ONLY permitted entries are (i) the read INSIDE `CarrierStrategy.observe()` / `GenericStrategy.observe()`, (ii) explicit display-only sites annotated in-source with `# preset_mode: display-only — <reason>` (the lint reads the source line's trailing comment to confirm the annotation matches the allowlist). Any new raw read WITHOUT an allowlist entry AND an in-source annotation is a lint failure.

Rationale for the split: the behavioural anchor proves each specific reader routes through classify TODAY; the AST lint prevents the class-of-defect from returning tomorrow. Together they satisfy `feedback_wire_in_anchor_mandatory` (per-site enclosing-method anchor) and `feedback_hollow_test_anchors` (no grep-only completeness).

Consumer table (trust vs display):

| Consumer | File:line | Role | Uses `Strategy.classify` | Behavioural anchor test |
|---|---|---|---|---|
| S1 preset dispatch | `hvac.py:2013, :2674` | trust | YES via `should_change_preset` | `test_s1_dispatch_follows_classify_not_raw_preset_mode` |
| Arrester override detect | `hvac_override.py:2304-2340` | trust | YES (also uses `detect_human_change`) | `test_arrester_override_detect_follows_classify_and_discriminator` |
| Arrester revert | `hvac_override.py:3519/3547` | trust | YES | `test_arrester_revert_gates_on_classify` |
| Retreat-decision helpers | `hvac_zones.py:512` | trust | YES | `test_retreat_helper_follows_classify` |
| Arrester diagnostics strings | `hvac_override.py:2056, :2451-2453, :2978-2991, :4683, :4770, :5660, :5892` | display | RAW allowed | (allowlisted; no behavioural anchor needed) |
| Diagnostics attrs | `coordinator_diagnostics.py:494-495, :554` | display | RAW allowed | (allowlisted) |

The AST lint's allowlist enumerates every `display` row above (with reason `display-only diagnostic string`), plus the two `observe()` implementations. Every other match is a failure.

**Acceptance for D2.6:**
- Each of the four behavioural anchor tests above passes today AND goes RED under Reviewer C mutation at its specific site.
- `test_hvac_preset_mode_read_completeness` passes on `develop` today (with an allowlist populated from the migrated code) AND fails when a new raw read is added anywhere under `hvac*.py`.
- Cross-check: the AST lint's allowlist size equals the display-only rows in the consumer table + the two `observe()` implementations; drift is a lint failure.

#### D2.8 28-site write table (Reviewer #1 HIGH — REV 4 full table)

Every URA-originating thermostat write, its verb, its Strategy method OR direct-funnel-with-reason exemption, and which gates it consults.

| # | Site (file:line, refresh at build-start) | Verb | Strategy method OR direct funnel + reason | Gates consulted |
|---|---|---|---|---|
| 1 | S1 house-state preset dispatch `hvac.py:2674` | set_preset_mode | `Strategy.hold_preset` | BORROW_LOCK, classify, `_corrective_writes_suppressed`, no-op |
| 2 | `heat_cool` enforcer `hvac.py:1926-1938` | set_hvac_mode | direct `emit_set_hvac_mode` (reason: "hvac_mode is not a hold; no classify path") | none beyond funnel |
| 3 | S3 arrester compromise start `hvac_override.py:3393` | set_temperature | `Strategy.borrow(kind=COMPROMISE)` | `_corrective_writes_suppressed`, freeze |
| 4 | S4 arrester revert setpoint `hvac_override.py:3531` | set_temperature | `Strategy.return_borrow` (presets-only after D2.4) | BORROW_LOCK (borrow-owned by excursion_id), `_corrective_writes_suppressed` |
| 5 | S4 arrester revert preset `hvac_override.py:3561` | set_preset_mode | `Strategy.return_borrow` | same |
| 6 | Hard reset off/on `hvac_override.py:3888` | set_hvac_mode | direct `emit_set_hvac_mode` (reason: "hard reset off/on is not a hold") | none beyond funnel |
| 7 | Hard reset restore #1 `hvac_override.py:4028` | set_temperature | `Strategy.return_borrow` | as (4) |
| 8 | Hard reset restore #2 `hvac_override.py:4067` | set_preset_mode | `Strategy.return_borrow` | as (4) |
| 9 | Hard reset restore #3 `hvac_override.py:4142` | set_preset_mode | `Strategy.return_borrow` | as (4) |
| 10 | S5 soft nudge START setpoint `hvac_override.py:4423` | set_temperature | `Strategy.borrow(kind=NUDGE)` | `_corrective_writes_suppressed` (nudge starts NEVER gated by BORROW_LOCK — nudge start is what ARMS it) |
| 11 | S6 nudge restore setpoint `hvac_override.py:4633` | set_temperature | (DROPPED in D2.4 migrated edit; if HUMAN_MANUAL discriminator fires, method returns pre-any-write per D2.1 C3) | classify, BORROW_LOCK exemption via `excursion_id` |
| 12 | S7 nudge restore preset `hvac_override.py:4681` | set_preset_mode | `Strategy.return_borrow` | classify, BORROW_LOCK exemption via `excursion_id`, no-op |
| 13 | S8 cancel-nudge setpoint `hvac_override.py:5860` | set_temperature | `Strategy.return_borrow` | as (4) |
| 14 | S8 cancel-nudge preset `hvac_override.py:5889` | set_preset_mode | `Strategy.return_borrow` | as (4) |
| 15 | S9 boot audit setpoint `hvac_override.py:6272` | set_temperature | `Strategy.return_borrow` | as (4) |
| 16 | S9 boot audit preset `hvac_override.py:6296` | set_preset_mode | `Strategy.return_borrow` | as (4) |
| 17 | S10 DPM custom ranges `hvac.py:3046` | set_temperature | direct `emit_set_temperature` (reason: "DPM baseline write, exempt from Strategy — F8 exemption") | `_corrective_writes_suppressed`, freeze |
| 18 | S11 banking START `hvac_predict.py:976` | set_temperature | `Strategy.borrow(kind=BANKING)` | freeze; NOT BORROW_LOCK (banking not locked) |
| 19 | S11 banking release setpoint `hvac_predict.py:984` | set_temperature | `Strategy.return_borrow` | as (4) |
| 20 | S11 banking release preset `hvac_predict.py:1046` | set_preset_mode | `Strategy.return_borrow` | as (4) |
| 21 | S12 pre-cool `hvac_predict.py:1160` | set_temperature | `Strategy.borrow(kind=PREHEAT)` (variant; today catalogued as pre-cool) | freeze; NOT BORROW_LOCK |
| 22 | S13 pre-heat START `hvac_predict.py:1448` | set_temperature | `Strategy.borrow(kind=PREHEAT)` | freeze; NOT BORROW_LOCK |
| 23 | S13 pre-heat mid `hvac_predict.py:1511` | set_temperature | `Strategy.borrow(kind=PREHEAT)` cont. | as (22) |
| 24 | S13 pre-heat release setpoint `hvac_predict.py:1520` | set_temperature | `Strategy.return_borrow` | as (4) |
| 25 | S13 pre-heat release preset `hvac_predict.py:1570` | set_preset_mode | `Strategy.return_borrow` | as (4) |
| 26 | Egress pause `hvac_egress.py:683` | set_hvac_mode | direct `emit_set_hvac_mode` (reason: "mode change for pause is not a hold") | none beyond funnel |
| 27 | Egress resume setpoint `hvac_egress.py:794` | set_temperature | `Strategy.return_borrow` | as (4) |
| 28 | Egress resume preset `hvac_egress.py:815` | set_preset_mode | `Strategy.return_borrow` | as (4) |

Also-in-strategy (site 29, added by D2.3-R): **URA-owned reclaim write** — `Strategy.hold_preset` called from the ProvenanceStore / decision-cycle path when all D2.3-R conditions are met. NOT a source site in the enumeration above (invoked from the decision loop, not a fixed line); tracked in `climate_write` by `site="S1_ura_owned_reclaim"` and `reason="ura_owned_manual_reclaim"`.

Verify at build-start: `git grep` `emit_set_temperature\|emit_set_preset_mode\|emit_set_hvac_mode` outside `hvac_setpoint.py` returns EXACTLY these 28 lines. The 29th (URA-owned reclaim) is inside the strategy call chain and appears via Strategy.hold_preset only. Any drift → refresh this table in the SAME commit.

#### D2a — Split `_last_emitted_range` (problem 5, finding #5 / F8)

Today `_last_emitted_range` at `hvac.py:521` does TWO jobs (funnel no-op + S10/DPM baseline). Split:
- `Funnel.last_sent[entity_id][verb]` — no-op suppression (D2.5), inside `hvac_setpoint.py` / `hvac_strategy.py`.
- `HvacZoneBaseline[zone_id]` — S10/DPM zone-keyed comfort baseline, its own tiny helper module, preserving byte-identical reader/writer semantics for `hvac_predict.py:889/943/1526` and `hvac.py:429/521/3023/3068`.
- **F8 exemption:** S10 baseline writer is EXEMPT from ProvenanceStore reclaim — its writes are baseline-recomputes, not overrides.

Acceptance: `test_zone_baseline_split_semantics` — reads/writes byte-for-byte pre-migration.

### D4 — Module constants + URA-owned reclaim knobs (binding decision 3 RESTORED; binding decision 6 rung placement)

**Rung 1 (module constants, review-only):**

| Constant | Value | Rationale |
|---|---|---|
| `BORROW_LOCK_HARD_CAP_S` | 600 (10 min) | Operator decision 9 — hard cap; nudges 2 min, compromises 5-6.4 min all fit; banking/pre-cool NOT locked |
| `URA_OWNED_TOLERANCE_F` | 0.5 | Device displays whole degrees; half a unit tolerance |
| `STRAND_WINDOW_S` | 400 (seed; D0-confirmed before D2 merges) | Post-restore strand window; sized from echo-fix Review B (~300-370 s) |
| `URA_OWNED_RECLAIM_DELAY_S` | 0 (default; "1 tick" — same-tick eligible) | Binding decision 3 (2026-09-26). Rung 1 (module const, review-only) per binding decision 6. |

**Rung 3 (Switch entity, RestoreEntity):**

| Entity | Default | Semantics |
|---|---|---|
| `switch.ura_hvac_coordinator_ura_owned_manual_reclaim_enabled` | **ON** | Binding decision 3. ON: reclaim per D2.3-R fires. OFF: no reclaim; S1's `URA_OWNED_MANUAL` classification is honest (visible in diagnostics) but the reclaim WRITE is disabled — distinguishes "off" from "very delayed." Live-tunable via HA UI; RestoreEntity so it survives restart. Persisted via the standard URA switch platform (`switch.py`). |

No `POST_WRITE_INTERCEPT_S`, no `PRESET_TTL_S`, no `CONFIRMATION_WINDOW_S`, no `CONFIRMATION_RETRY_MAX`, no `CONFIRMATION_RETRY_BACKOFF_S` (all confirmation-oracle scope, removed with problem 6 → `HVAC-WRITE-CONFIRMATION-ORACLE-1`).

**Acceptance:**
- Kill switch entity exists post-restart with default ON, `RestoreEntity` persistence proven across restart.
- `URA_OWNED_RECLAIM_DELAY_S` const at Rung 1, no operator UI exposure (per binding decision 6); a code change is required to move off same-tick.
- Discriminating: kill switch OFF blocks reclaim (D2.3-R test); delay = 0 fires same tick; delay = 120 fires after 2 ticks; NOT the same as kill switch OFF (test contrast).

### D5 — Fully specified generic default (unchanged from REV 3 minus oracle trivial branch)

For any thermostat NOT `ha_carrier`:
- `hold_preset` = direct pin (no `resume` — Carrier vocabulary).
- `borrow` = optimistic snapshot from `observe()`; `set_temperature` + `set_preset_mode`.
- `return_borrow` order: **mode → preset → setpoints only if entity advertises NO `preset_modes`**.
- `observe()` reads standard climate attributes; `hold_activity` may be `None`; classifier treats absent hold as `NO_HOLD` and never emits URA-owned inference over an entity without writable presets.
- `classify()` uses provenance-only:
  - `set_temperature` W1-A record in-window whose `values_after` matches observation setpoints AND `observation.preset_mode is None` (or the thermostat's manual-equivalent) → `URA_OWNED_MANUAL`.
  - Setpoint drift with no W1-A record in the interval → `HUMAN_MANUAL`.
- No-preset thermostats: `hold_preset` → `WriteResult(status=FAILED, reason='no_presets_supported')`; caller uses setpoints-only fallback.

**Non-goal:** no Nest strategy code. Interface accepts one.

Acceptance tests (kept from REV 3): `test_generic_default_no_resume_emitted`, `test_generic_default_setpoint_drift_is_human`, `test_generic_default_no_presets_fallback`.

---

## 6. Operator questions

Q1-Q7 remain RESOLVED by REV 3's binding decisions 1-7 (nudges on set_temperature; operator reduces schedules; **binding decision 3's reclaim DELAY + separate kill switch RESTORED per orchestrator re-review — these govern the URA-owned reclaim of problem 1 / 5, NOT the parked knob-expiry reclaim of former problem 4**; N≥10 non-nudge exercised episodes per zone; no Nest stub; module constants stay Rung 1; decision 7 has no consumer this cycle per operator decision 8). Q8-Q9 (confirmation-oracle scheduling and `[CONFIRMATION EXHAUSTED]` NM behaviour) are OUT OF SCOPE — carded on `HVAC-WRITE-CONFIRMATION-ORACLE-1`.

**Open questions for this REV 4:** aim for none. If a Tier-3 plan review surfaces one, it belongs here.

---

## 7. Ship gate — disposition query, not soak

**Pre-deploy gate — replay.** After D0 output is folded into D2, run the D2 matrix against the strategy code in test. If the replay produces any strand-equivalent (URA-owned manual + lockout ledger row) OR any of the D2.4 per-site source mutations does NOT produce a specific test failure, deploy is BLOCKED.

**Post-deploy disposition query at N≥10 non-nudge return episodes per zone (7-day cap).**

| Conjunct | Query | Pass criterion |
|---|---|---|
| C1 | Count `climate_write` rows where `verb=set_temperature` AND `site` matches a §5 D2.4 return site AND `reason` NOT HUMAN_MANUAL | 0 |
| C2 | Join `climate_write` × open `_rows[zone_id]` (NUDGE / COMPROMISE) per entity, exclude rows carrying live token `excursion_id`, exclude any preceded by `[BORROW LOCK CAP HIT]` NM within 10 min | 0 |
| C3 | Within the D0-sized `STRAND_WINDOW_S` post lock-arm on a NUDGE / COMPROMISE that got a genuine human change (per D2.3 discriminator), count return writes | 0 |
| C4 | Count `preset_change_locked_out` rows where the immediately preceding W1-A `climate_write` on the entity matches the observed manual within `URA_OWNED_TOLERANCE_F` AND `hold_activity` post-dates URA's write AND `detect_human_change` returns None | 0 |
| C5 | Count `climate_write` rows with `wire_ok=True` AND `values_before` == `values_after` | 0 |
| C6 | (Kill switch ON) For every `URA_OWNED_MANUAL` classification with no live borrow and no corrective-writes suppression, measure time from classification to the `S1_ura_owned_reclaim` `climate_write` row on the entity. Any interval > `URA_OWNED_RECLAIM_DELAY_S + tick_period` fails. AND (kill switch OFF) count of `S1_ura_owned_reclaim` rows across the disposition window MUST be 0. | 0 |

- Query = one SQL against `ura_activity_log` (incl. `climate_write`) + `hvac_excursion_events` + kill-switch state history at disposition time. NOT a calendar watch.
- PASS → dispose the card. FAIL with unmet floor → extend the window. FAIL with a falsifier fire → reopen, analyse, plan a fix-forward or roll back.

---

## 8. Review protocol (Tier 3 — 4 framing-disjoint reviews + orchestrator hand-check + operator checkpoint)

Per CLAUDE.md Tier 3 + operator standing policy.

- **Reviewer A — local correctness.** Strategy branch logic; ProvenanceStore `classify` matrix (per-conjunct arithmetic); `detect_human_change` boolean lattice; presets-only return per site; per-site edit correctness; tri-state `WriteResult` handling at every call site; the `URA_OWNED_TOLERANCE_F` + `STRAND_WINDOW_S` arithmetic vs D0 output; D2.8 28-site table cell-by-cell; **D2.3-R URA-owned reclaim** trigger arithmetic (six gate conditions) + delay+tick timing; kill-switch semantics distinct from "very delayed."
- **Reviewer B — integration / state-machine integrity.** BORROW_LOCK derivation actually reads LIVE state (Reviewer #2 CRIT-4); the 10-min hard cap discharges (NM latched, dedup, sweep picks up the row); the human-ends-borrow path at `hvac_override.py:4617-4700+` correctly suppresses BOTH `:4633` AND `:4681`; restart rebuild correctness (ProvenanceStore + Funnel.last_sent + `classification_first_seen_ts` re-seed); no regression on `HUMAN_MANUAL` lockout; no interaction with the parked `HVAC-EXCURSION-RESTORE-UNIFIED-1`; failed-return retry with discharge and gate pass-through; the human discriminator is echo-safe under `SUPPRESS_TTL_SECONDS` changes; **URA-owned reclaim path routes through the SAME funnel** so D2.5 no-op applies; kill switch RestoreEntity survives restart; C6 does NOT re-fire spuriously on a classification that oscillates (add a hysteresis test if the tick shape allows).
- **Reviewer C — test authority via REAL per-site source mutation.** Each of the 19 D2.4 sites + each of the 28 D2.8 sites gets its own mutation drill; global monkeypatch is NOT sufficient. Bytecode disabled + `__pycache__` cleared each drill. Independent re-derivation of the site list. Additionally mutate: BORROW_LOCK derivation (per source); the human discriminator's three conjuncts (each independently); `URA_OWNED_TOLERANCE_F`; `BORROW_LOCK_HARD_CAP_S`; `URA_OWNED_RECLAIM_DELAY_S`; the kill-switch read site. **AND the D2.6 behavioural anchors: each of the four trust-reader anchors goes RED under a per-site mutation that bypasses the Strategy call.** Each mutation MUST produce a specific named test failure.
- **Reviewer D — adversarial completeness / diff-blind.** Restate INV-W1B (REV 4 — six conjuncts C1-C6) in reviewer's own words; re-enumerate the ENTIRE thermostat-write surface across `hvac*.py` — INCLUDING pre-existing code, not just the diff — for any missed borrow-return site, any writer that bypasses the strategy, any classifier consumer that reads `preset_mode` raw without going through `observe()`. D also re-enumerates every path that CLOSES an excursion row and confirms `human_ended_no_restore` outcomes are surfaced. D adversarially probes the human discriminator (whole-degree tolerance edges). **D confirms the D2.6 AST completeness lint's allowlist is a strict subset of the consumer table's display rows + the two `observe()` implementations; any drift is a finding.** D confirms the URA-owned reclaim (C6) has no path that fires while a borrow is live OR under TAO/immune OR with kill switch OFF.

**Two plan reviews on THIS document, before build dispatch (Tier 3 mandate):**
1. **Plan Reviewer 1 — completeness.** Re-enumerate every thermostat-write site independently (`git grep` on `hvac_setpoint` imports across `hvac*.py`) and confirm each appears in D2.8's 28-site table with the correct Strategy method / direct-funnel-with-reason / gates. Confirm D0's four outputs each seat a specific D2 fixture / constant / test. Confirm INV-W1B's SIX conjuncts (C1-C6) are individually falsifiable and each has a matching §7 ship-gate query row. Confirm the D2.6 completeness lint is AST-based (not grep) and its allowlist is enumerated. Confirm the URA-owned reclaim kill switch is a real `SwitchEntity` with `RestoreEntity`.
2. **Plan Reviewer 2 — adversarial build-prediction.** Predict what a builder will get wrong reading REV 4: does the plan clearly say BORROW_LOCK is derived from LIVE state and NOT from `_override_active`? Does it clearly say `human_ended_no_restore` closes the excursion row with NO write, and that this applies to BOTH `:4633` AND `:4681`? Does it clearly say the human discriminator is echo-safe and must NOT rely on `override_detected` alone? Does it clearly say `STRAND_WINDOW_S` is a D0 output, not a hardcode? Does it clearly say the URA-owned reclaim (C6) is DISTINCT from the parked knob-expiry reclaim (former D3)? Does it clearly say the D2.6 completeness lint is AST-based, not grep-based? Where the plan offers "either X or Y" (should be nowhere), lift to §6. Any place a builder could reasonably wire in a confirmation oracle from REV 3 residue is a finding.

Plan-review findings are fixed IN THE PLAN before any build dispatch.

**Orchestrator hand-check before deploy (Tier 3 mandate).**
1. `git grep` re-run: every `climate.set_temperature` / `set_preset_mode` / `set_hvac_mode` service call outside the funnels MUST be zero.
2. Re-run the 19-site inventory against `Strategy.return_borrow`; every site maps; `hvac_excursion.py:1322` STILL no-write.
3. Re-run the 28-site table against `git grep` on funnel imports; delta = 0.
4. Real source mutation of `Strategy.return_borrow` on each of the 19 sites → suite RED with a specific named failure per site.
5. Real source mutation of BORROW_LOCK derivation sources — each RED with a specific test.
6. Real source mutation of the human discriminator's three conjuncts — each RED with a specific test.
7. Real source mutation of each D2.6 trust-reader anchor — each RED with a specific test.
8. Run the D2.6 AST completeness lint against `develop` at ship time; must PASS with the allowlist that ships in the test file.
9. Toggle `switch.ura_hvac_coordinator_ura_owned_manual_reclaim_enabled` in a test-harness run: ON fires reclaim on a URA_OWNED_MANUAL fixture, OFF does not; RestoreEntity survives an integration reload.
10. D0 replay in test — zero strand-equivalents on the fixture.

**Operator checkpoint BEFORE deploy.** Surface D-review outcome; the invariant proof (grep + mutation + replay + AST lint); the D0 findings (incl. confirmed `STRAND_WINDOW_S` and human-discriminator calibration); the 19-site coverage; the 28-site table; the kill-switch toggle demonstration; the four D2.6 behavioural anchors + AST lint passing. Explicit go required.

---

## 9. Sequencing / dependencies

1. Stage A ships (W1-A). **SHIPPED v5.103.16 2026-09-26.**
2. Echo-fix ships. **SHIPS v5.103.17 2026-09-27** (`SUPPRESS_TTL_SECONDS` 5 → 15, kind="temp" only).
3. Two plan reviews on this REV 4 (completeness + adversarial-build-prediction). Findings folded in place before build.
4. **D0 measurement gate.** Starts running ≥ 2 days after v5.103.17 ships. D0's `STRAND_WINDOW_S` + human-discriminator calibration + config-combination matrix are inputs to D2. Build MAY begin on D1 + D4 + D5 in parallel; D2 does NOT MERGE until D0 completes.
5. Build in isolated worktree `.claude/worktrees/hvac-w1b-thermostat-definition` on `feature/hvac-w1b-thermostat-definition` off latest `develop`.
6. Build order: **D1 + D4 (incl. kill switch entity) + D5 → D0-freeze → D2 (full; includes D2.3-R URA-owned reclaim, D2a split, D2.6 behavioural anchors + AST lint, per-site D2.4 edits).**
7. Four framing-disjoint reviews on the D1-D5 build in parallel. Fix CRITICAL / HIGH; re-run D's enumeration; orchestrator hand-check (§8).
8. Operator checkpoint. On go: deploy.
9. Live-validation write-back into `README_v<version>.md`.
10. Post-deploy disposition query at N≥10 non-nudge return episodes per zone (§7 — all SIX conjuncts).
11. Separately (not this cycle): the orchestrator's new card `HVAC-WRITE-CONFIRMATION-ORACLE-1` holds the D0 physical-truth probe extension + operator controlled test + oracle DATA design. Not blocking this cycle.

**No soak.** The ship gate is a disposition query, not a calendar watch.

---

## Operator decisions — BINDING

**REV 3 (2026-09-26 "Accept recs") — verbatim, do not edit; annotations added beside where scope changed:**
1. `set_activity_setpoint` NOT adopted this cycle — nudges stay on `set_temperature`.
2. No in-code schedule-boundary guard — operator reduces zone 2/3 Bryant schedules.
3. **Reclaim DELAY for a URA-owned manual hold with no live borrow = 1 tick (same-tick eligible), plus a separate kill switch.** [REV 4 annotation: RESTORED per orchestrator re-review 2026-09-26. This governs the URA-owned reclaim of problem 1 / 5 (INV C6, §5 D2.3-R, §5 D4) — DISTINCT from and NOT removed by decision 8's removal of the former D3 knob-expiry reclaim (former problem 4). The first REV 4 draft wrongly conflated them; this REV 4 restores the delay + kill switch.]
4. Ship-gate disposition: N ≥ 10 exercised return episodes per zone, 10-min falsifier window; pre-deploy gate = replay.
5. No Nest stub.
6. `POST_WRITE_INTERCEPT_S` / `PRESET_TTL_S` (and sibling timing values) are Rung 1 module constants. [REV 4 annotation: `URA_OWNED_RECLAIM_DELAY_S` is likewise Rung 1 (const, review-only) per this rung placement; only the kill switch is Rung 3 (SwitchEntity), because a kill switch is exactly the "legitimately turn it, per-deployment observable state" case the ladder reserves for Rung 3.]
7. On Temp-Arrester-Override / immune-person expiry against a HUMAN hold: reclaim to S1's current target preset (not a snapshot); Comfort Grace is not part of D3. [REV 4 annotation: former D3 REMOVED per decision 8; this decision therefore has NO consumer this cycle. Do NOT conflate with decision 3, which is a different reclaim path (URA-OWNED classification, not HUMAN-expiry release channel).]

**REV 4 (2026-09-26 evening):**
8. **Scope = problems 1, 2, 3, 5.** Problem 6 (confirmation oracle) REMOVED — separate measurement-only investigation (`HVAC-WRITE-CONFIRMATION-ORACLE-1`, being minted by orchestrator 2026-09-26). Problem 4 (reclaim on TAO / immune-person expiry — the former D3) REMOVED and PARKED (data: 22 auto expiries, 0 `preset_change_locked_out` within 3 h). Revival trigger = a lockout within 3 h of an expiry. Decision 7 therefore has no consumer this cycle. **Decision 3's URA-owned reclaim (a DIFFERENT reclaim path — URA-owned classification, not human-expiry) is IN scope.**
9. **Borrow lock applies ONLY to nudges and compromises** with a hard cap of 10 min. Banking, pre-cool, pre-heat, egress are NOT locked. Build the lock from the REAL live borrow state (`_rows[zone_id]` for compromise; `_nudge_excursion_tokens` / `_nudge_restore_timers` for nudges) — NOT `_override_active`. The borrow's own return writes are exempt via `excursion_id` match. At the cap: lock ends, normal writers resume, one NM.
10. **A genuine human change during a locked borrow ENDS that borrow with NO return write.** Fix today's nudge restore (`hvac_override.py:4617-4700+`, incl. corrective-gate exception `:4622-4640` and unconditional preset write `:4674-4685`) which currently writes the pre-nudge setpoint over a person in the 2 min window. "Genuine" MUST use the echo-safe discriminator (detection only after the 15 s temp-kind window; `override_detected` alone is necessary but NOT sufficient — see §5 D2.3 three-conjunct discriminator).
11. **Problem 1 solution:** (a) presets-only returns on EVERY real return path (verified 19-site inventory, §5 D2.4; row `hvac_excursion.py:1322` STAYS no-write — verify every line on current `develop` at build-start); (b) in-memory W1-A last-write record per entity (verb, APPLIED values post freeze-floor / deadband, issue wall-time) exposed as a small read API — the provenance primitive. A manual hold appearing after URA's last write, at URA's restored setpoints (tolerance ±0.5 °F), with no genuine human change in between, is URA-owned → reclaimed **per binding decision 3's delay + kill switch (§5 D2.3-R, INV C6)** instead of locking URA out. MUST NOT rely on `override_detected` alone as human evidence. Strand window sized from data — post-restore residuals ~300-370 s after `nudge_restored`; D0 confirms `STRAND_WINDOW_S` (seed 400 s).
12. **CONFIG-FIRST (new standing rule):** every plan proves that no operator setting change alone fixes the target problems. §0.2 enumerates the relevant live knobs and demonstrates each is insufficient.
