# PLANNING — HVAC W1-B: Per-brand thermostat definition (Carrier/Bryant first) — REV 3

**Card:** `HVAC-W1-THERMOSTAT-DEFINITION` (Stage B).
**Tier:** **Tier 3** (delicate; threads a shared primitive across ~10 return sequences; single-missed-site is the exact failure class the parked `HVAC-EXCURSION-RESTORE-UNIFIED-1` cycle exhibited; REV 3 adds a write-confirmation oracle whose wrong answer either strands zones or overwrites humans — a canonical trust-hierarchy ripple).
**Depends on:** W1-A (`HVAC-SETHVACMODE-CHOKEPOINT-1` + one durable write log) — **SHIPPED v5.103.16 2026-09-26** (`docs/readmes/README_v5.103.16.md`). `climate_write` now records `values_before` including `preset_mode` AND `hold_activity` read synchronously before every URA thermostat write, plus `values_after`, `wire_ok`, `site`, `zone_id`, `reason`, `excursion_id`, `ts_issued`/`ts_returned`. One clean day of `climate_write` rows remains a hard input to this cycle's D0 probe.
**Operator posture:** nudges stay ON; AC ramp ON; per-brand behaviour discovered in detail behind a simple generic interface; Tier-3 double-checkpoint (before build AND before deploy).
**Reference reads (mandatory, complete, before doing anything):**
`docs/Coordinator/HVAC_ARCHITECTURE_STATE_OF_PLAY.md` (all sections — **§9.7 (zone_1 status=home while hold=away, physically away, Carrier reload does NOT fix it, URA re-writes away ~6/h)** and **§10 corrections ledger C20 / C21 / C22** especially),
`docs/Coordinator/THERMOSTAT_DEFINITION_CARRIER_BRYANT.md` rev 2 (companion, ships D0 of this cycle),
`docs/readmes/README_v5.103.16.md` (W1-A ledger row shape — the values_before/values_after schema this cycle consumes),
`scripts/probes/carrier_feed_truth_probe.py` + `scripts/probes/carrier_feed_truth_episodes.py` (the C22 method: physical blower + zone temperature vs each feed's cooling setpoint with a 2 °F differential guard, episode-pooled by disagreement class).

## Rev-3 change log — why REV 3 exists

REV 2 was written on the premise (C20) that when the two Carrier feeds disagree, the CONFIG feed (`hold_activity`) is authoritative — encoded in the D2.3 classifier ("a config-manual observation AFTER a URA named write is always HUMAN"; the retirement of `SUPPRESS_TTL_SECONDS_PRESET`; the "trust `hold_activity`" corollary the classifier leaned on). **C22 (2026-09-26 afternoon) refutes that premise with physical evidence:**

- 7 d physical-truth probe (`scripts/probes/carrier_feed_truth_episodes.py`) across zone_1 / zone_2 / zone_3: blower state + zone temperature vs each feed's cooling setpoint, 2 °F differential guard, decisive minutes pooled by disagreement class.
- **Named-vs-named disagreement (zone_1 status=home / hold=away, §9.7):** device followed **HOLD 85 min** vs **STATUS 5 min**. Physical verification 13:10 (blower 0 for 4 h, zone rose 76→80 °F, operator app "Holding Away 68-80, Idle"). Integration reload 13:20 did NOT clear it. Trusting the status feed here = ~6 stale re-writes/h (§9.7 churn).
- **Status=`manual` after a GENUINE human override (zone_2, 2026-09-26 00:45, human set cool 70 in the Carrier app, arrester logged an `override_detected` row):** device followed **STATUS 506 min** vs **HOLD 4 min**. `hold_activity` read `sleep` for 8.5 h while the zone actually cooled to 71-74 °F. Trusting the hold feed here = URA reclaiming a real human hold. This is the exact failure the REV 2 classifier permits.
- **Status=`manual` after URA borrows (zone_1 strands, §9.1):** device followed **HOLD 21 min** vs **STATUS 1 min**. Trusting the hold feed here = the correct REV 2 behaviour.

**Neither feed is universally right.** REV 2 encoded one of the two wrong universals. REV 3 introduces PROBLEM 6 and lifts the confirmation-oracle decision into DATA per brand (the CarrierStrategy), driven by two inputs it already has:

1. W1-A `climate_write.values_before` (the just-before-write `preset_mode` AND `hold_activity` snapshot — v5.103.16 ledger).
2. The arrester's `override_detected` row (`ura_activity_log`) — the existing genuine-human-override discriminator (§7).

The rule the CarrierStrategy TESTS (candidate, UNPROVEN at n=1 per case): **trust `hold_activity` unless a genuine human override is detected on this entity within the confirmation window, then trust the STATUS payload.** D0 promotes this rule from candidate to design-frozen input via the probe over the first clean day(s) of W1-A rows AND a controlled operator app-change test.

REV 3 also fixes the §9.7 write-churn symptom by construction: if the confirming feed already shows the intended preset, URA does not re-issue — with a bounded retry discharge so a genuinely un-applied preset is still re-sent.

| Change | Where folded |
|---|---|
| PROBLEM 6 (write-confirmation oracle) added | new §0.1, new sub-deliverable §5.D2.7 (justified below), §3 D0 extension, §7 ship-gate query extension, §2 non-goals updated |
| INV-W1B extended with two new conjuncts (no re-issue when oracle confirms; no overwrite of a genuine human) | §0 |
| D0 extended with physical feed-truth probe + operator controlled-test input | §3 |
| D2 classifier rewired: `hold_activity`-authority CLAIM DELETED; oracle is DATA per brand fed by W1-A `values_before` + arrester override-detection | §5.D2.3 replaced, §5.D2.7 added |
| D2.5 no-op suppression extended: NEVER re-issue a preset the confirming feed already shows | §5.D2.5 |
| Ship-gate disposition query: `climate_write` re-issue rate per zone must fall to ~0 on the §9.7 case, zero human-override overwrites | §7 |
| Two plan reviews retargeted at REV 3 (oracle-completeness + oracle-adversarial) | §8 |
| §9.7 explicitly folded into the invariant surface | §0 note, §5.D2.7 |
| C22 folded into corrections-referenced list | §1.4 |
| README v5.103.16 folded into references and D0 data sources | header + §3 |

REV 2's rev-1 fold table (below) is kept verbatim for provenance.

---

## Rev-2 change log — how the two Tier-3 plan reviews folded (kept from REV 2)

Both plan reviews returned **FIX-PLAN-FIRST**; every finding is folded into the corresponding
section here (nothing is deferred without a card). The rev-1 plan proposed a status/config
coherence classifier as the load-bearing fix; a tonight measurement (C20, state-of-play §9.1)
refuted that premise. This rev drops the coherence classifier entirely, moves ownership to
PROVENANCE, and folds every numbered finding.

| Finding | Where folded |
|---|---|
| C20 refutation of coherence classifier | §0 invariant (new), §5.D2 ownership, §4 review D scope, deletion of `URA_ECHO_MANUAL` and profile-match classifications |
| C16 shared-account guard wipes | §3 D0 probe, §5.D2 window model, §6.F9 window discharge table |
| C17 preset TTL = 120 s (not 5 s) | §5.D2 ownership window, retirement note (retire `SUPPRESS_TTL_SECONDS_PRESET` only, keep the 5-s temp TTL) |
| F16 spec corrections | companion doc rev 2 (2-API-call set_temperature; HEAT_COOL raise; set_activity_setpoint DOES open a guard, edits STATUS-named activity; hold_activity is NOT authoritative for provenance; guard wipe triggers; 3 single-zone systems under 1 account) |
| #1 BORROW_ACTIVE gate | §5.D2 (S1 + arrester make no write while a live excursion or in-flight nudge exists for the entity) |
| #2 snapshot correctness | §5.D2 snapshot rule (use coherent/provenance-aware read; setpoints+preset fallback only for a genuine human manual snapshot; INV carve-out) |
| #3 provenance-based ownership, delete profile-match | §5.D2 classifier (`observe()` returns `HoldObservation`; `classify()` uses ProvenanceStore, not profile match) |
| #4 reclaim knob = DELAY + kill switch | §5.D4; operator Q3 restated |
| #5 no-op suppression rule + zone-keyed S10/DPM baseline accessor as its OWN concept | §5.D2 suppression rule; §5.D2a S10/DPM baseline concept (`hvac_predict.py:889/943/1526`, `hvac.py:429/521/3023/3068`) |
| #6 one bounded re-assert per episode | §5.D2 reclaim caps |
| #7 full window spec — CLASSIFICATION-ONLY, never blanket suppression | §5.D2 window table + retirement notes |
| #8 Q7 (reclaim HUMAN hold to S1's current target on TAO/immune-person expiry?); remove Comfort Grace from D3 | §6 Q7 added; §5.D3 revised |
| #9 restart rebuild | §5.D2 ProvenanceStore boot rebuild from `hvac_excursion_state` + W1-A `climate_write` last row |
| #10 failed-return retry with discharge + gate pass-through | §5.D2 return path retry contract |
| #11 disposition query with exercised-episode floor N≥10; falsifier threshold 10 min; pre-deploy gate = replay | §7 ship gate |
| #12 brand lookup by entity-registry platform, cached per BRAND, never cache fallback | §5.D1 dispatch rule |
| #13 generic interface — `observe / hold_preset / borrow / return_borrow` with `borrow ⊇ begin_excursion` (gate, duration, freeze) | §5.D1 interface |
| #14 fully specified generic default (setpoint-drift human detection; no-preset thermostats; return order) | §5.D5 |
| #15 return order = mode -> preset -> (setpoints only if no presets) | §5.D2 + §5.D5 |
| #16 D2 replaces each site's inline pair in the same edit + per-site service-call-count test | §5.D2 migration & D6 folded into D2 (no separate D6) |
| #17 correct S1 wiring (`hvac_preset.py:212-217`, `hvac.py:2479`, `:2509`) + C3 grep test naming `observed_hold` | §5.D2 wiring table |
| #18 config-combination matrix | §3 D0 output shape + §5.D2 test matrix |
| #19 / #20 fixes | absorbed into §5.D2 wording |
| F1 exclusion re-derivation (rev-6 lease-strip fires) with live-token axis + per-kind falsifier tests; name tokenless URA manual writers S9 `hvac_override.py:6221` and S10 `hvac.py:3046` | §5.D2 BORROW_ACTIVE derivation + §5.D2 site enumeration (S9/S10 explicit) |
| F2 = #5 | see #5 |
| F3 snapshot sites | §5.D2 snapshot inventory |
| F4 full consumer table with trust/display column | §5.D2 consumer table + `preset_mode` grep gate |
| F5 = #3 | see #3 |
| F6 gate every reclaim on `_corrective_writes_suppressed` + active comfort grant | §5.D3 reclaim guard |
| F7 verified site table (11 preset / 10 temperature / 7 raw mode; 10 return sequences incl. S4, hard reset 4008/4043/4113 into INV, `_auto_return` `hvac_excursion.py:667/750/1188`, boot nudge restore `:1131`, auto_release_on_incomplete `:1322`); mode in `return_borrow` | §5.D2 verified inventory (replaces rev-1 "~11") |
| F8 S10 ownership class exempt from reclaim | §5.D2 S10/DPM exemption |
| F9 window model per C16 (shared-account guard; NEVER protects `hold_activity`; mode writes snapshot stale status); kept/retired window table | §5.D2 window table |
| F10-F15 | absorbed into §5 corresponding subsections |
| F16 definition-doc corrections | companion doc rev 2 |
| BP #1 build-prediction ambiguity from rev 1 | §5 ordering explicit; every "either X or Y" is either specified or lifted to §6 as a Q |

---

## 0. Falsifiable invariant (state up front — reviewer D's target)

> **INV-W1B (REV 3):** For every URA-initiated borrow that returns cleanly on a Carrier/Bryant zone,
> no Carrier-side manual hold appears at URA's own written values within the falsifier window
> (10 min after the return sequence completes) AS DETERMINED BY THE BRAND'S CONFIRMATION ORACLE (§5.D2.7).
> AND: URA never emits a preset lockout ledger row against an observed hold that URA's
> ProvenanceStore records as URA-owned.
> AND: while a borrow is live for an entity, S1 and the arrester write nothing to that entity.
> **AND (REV 3, new):** URA never re-issues a preset to a zone whose confirming feed (per the brand
> definition, §5.D2.7) already shows that preset within the confirmation window — measured as
> `climate_write` re-issue rate per zone falling to ~0 on the §9.7 case while a bounded retry
> discharge remains for genuinely un-applied writes.
> **AND (REV 3, new — symmetric):** URA never overwrites a genuine human manual by trusting the
> hold feed — measured as zero `climate_write` rows against a zone within the confirmation window
> of an `override_detected` row whose `values_before.preset_mode == "manual"` was set by a human
> (not preceded by a URA write of the same values inside the window).

Falsification shape: over the ship-gate exercised-episode floor (N≥10 non-nudge return sequences
plus every nudge return in a clean 72 h window on all three zones), zero episodes where a
manual-hold appears within 10 min of the return AND URA's ProvenanceStore identifies the observed
hold as URA-owned AND URA books a lockout instead of reclaiming; AND on the §9.7 zone_1 case,
`climate_write` re-issue rate falls to ~0 (from ~6/h) with the away preset held to physical truth;
AND across the 72 h window no `climate_write` row overwrites a `values_before.preset_mode="manual"`
observation whose provenance is HUMAN (i.e. no in-window URA write of the same values).

**INV carve-outs (explicit non-invariants):**
- A genuine `set_temperature` write by a human (dial or app) at values URA did not write is NOT
  URA-owned — those still lock URA out. This is correct behaviour and the REV 3 zone_2 00:45
  probe case IS this shape.
- The vendor-schedule race between `resume` and `pin` may still cause a brief unwanted state; see
  §6 Q2. Not this cycle's invariant.
- `HVAC-COMPOSE-AWAY-THROTTLE-STORM-BLOCKER-1` and `HVAC-RESTORE-WRITERS-STRAND-EMPTY-NIGHT-ZONE-1`
  are unblocked by moving `_last_emitted_range` ownership into the funnel (see §5.D2a) but the
  D9 dormant-switch enablement is not this cycle.
- No Nest strategy is landed. Interface accepts one; code lands only when hardware is available.
- `hvac_activity_log` writer-attribution across integrations is not solved (integration surface
  does not expose it).
- The confirmation oracle is a per-brand DATA definition — not a universal cross-brand rule. The
  generic default (§5.D5) still confirms optimistically from the observation only.

### 0.1 PROBLEM 6 — Write-confirmation oracle (which Carrier feed tells URA its write took)

Every URA thermostat write today is fire-and-forget: the funnel returns after the wire call, and
the next decision cycle re-reads the entity attributes and decides again. That works only if
**the attribute URA reads back is the attribute the device is actually following.** C22 shows
Carrier ships URA two attributes that disagree in physically-verifiable ways depending on the
disagreement class, and neither is universally the leader:

- Named-vs-named disagreement (both feeds name a preset, they disagree): the CONFIG feed
  (`hold_activity`) matches physical truth. Trusting STATUS here = §9.7 (URA re-writes AWAY
  ~6/h because STATUS shows `home`; device is physically AWAY).
- Status=`manual` after a genuine human override in the Carrier app: the STATUS feed leads.
  Trusting HOLD here would let URA reclaim a real human hold (the REV 2 classifier permits this).
- Status=`manual` after URA borrows (§9.1 strands): the HOLD feed leads. Trusting STATUS here
  would strand as REV 1 documented.

The confirmation oracle is the per-brand rule that picks the right feed for each disagreement
class, and thereby answers the operational question: **"did my write take, and if so, do I
need to re-issue?"** Getting it wrong in one direction strands zones; getting it wrong in the
other direction overwrites humans. This is a single point of trust that ripples through S1,
the arrester, the ProvenanceStore, and the reclaim path — and is why REV 3 is Tier 3.

Candidate CarrierStrategy oracle rule (n=1 per case, UNPROVEN — D0 promotes it):

> Trust `hold_activity` as the confirmation feed for a URA-issued preset write, UNLESS the
> arrester has booked an `override_detected` row on this entity within the confirmation window
> AND that row's `values_before.preset_mode == "manual"` was NOT preceded (within the same
> window) by a URA write of matching values — then trust the STATUS payload (`preset_mode`)
> until the next URA write.

D0 tests this rule against the probe's decisive-minute pool AND the operator's controlled
app-change (a known human case, tagged in `ura_activity_log`). If the probe disqualifies the
rule, the D2.7 CarrierStrategy oracle DATA is authored from the probe's discrimination table
directly rather than from this rule.

---

## 1. Institutional context verified

### 1.1 Prior-art scan (Tier 2+ mandate; every proposed piece cited REUSE-or-BUILD)

| Proposed piece | Verdict | Existing at |
|---|---|---|
| Preset-write "resume-then-pin" mechanism | REUSE | `hvac_setpoint.py:288-410`; `_needs_resume_first` `:181-226` |
| `climate.set_temperature` funnel | REUSE | `hvac_setpoint.py:229-286` |
| `climate.set_hvac_mode` funnel | REUSE (from W1-A) | `hvac_setpoint.py` `emit_set_hvac_mode` (shipped v5.103.16) |
| Durable per-write log | REUSE (from W1-A) | `ura_activity_log` `climate_write` row (shipped v5.103.16); `values_before` incl. `preset_mode` AND `hold_activity` |
| Excursion primitive `begin_excursion` / `return_excursion` (bookkeeping only) | REUSE — extend, don't replace | `hvac_excursion.py:766` / `:871-1040`; docstring `:886-888` |
| Excursion snapshot fields (`pre_preset`, `pre_target_low/high`, `pre_hvac_mode`, kind) | REUSE + extend read | `hvac_excursion.py` snapshot code + persisted `hvac_excursion_state` row |
| Per-entity runtime state (`_last_emitted_range` `hvac.py:521`; `_suppressed_until` `hvac_override.py:235`; `_nudge_pre_preset` `:262`; `_override_active` `:205`; excursion `_rows` `hvac_excursion.py:201`) | REUSE in place; ownership migrates for `_last_emitted_range` (see §5.D2a) | as cited |
| Suppression provenance tag `_suppress_kind` (`hvac_override.py:243-262`; nudge-only today) | REUSE + extend to all borrow kinds | as cited |
| BORROW_ACTIVE derivation (live excursion row + in-flight nudge) | BUILD from existing state | `hvac_excursion.py` rows + `hvac_override.py:_nudge_pre_preset` |
| Provenance-aware `observe()` and `classify()` | BUILD; no such helper today | uses W1-A `climate_write` + `hvac_excursion_state` rows |
| Presets-only borrow-return migration (10 return sequences, F7) | BUILD in same edit per site | see §5.D2 verified inventory |
| Per-brand strategy dispatch (memoized per BRAND via registry platform) | BUILD; minimal | HA entity registry |
| Zone-keyed S10/DPM baseline accessor as its OWN concept | BUILD as separate helper | today: `hvac_predict.py:889/943/1526`, `hvac.py:429/521/3023/3068` |
| **Write-confirmation oracle (per-brand DATA; §5.D2.7)** | **BUILD — per brand; Carrier first** | Inputs REUSE: W1-A `climate_write.values_before` (v5.103.16), `override_detected` row (`ura_activity_log`, arrester `hvac_override.py:2304-2340`) |
| **Genuine-human-override detection** | REUSE | arrester `override_detected` row (`hvac_override.py:2304-2340`) — already discriminates genuine humans from URA echoes for values-delta ≥ 1 °F, and REV 3 additionally joins to W1-A `values_before` to catch zero-delta human dial-back-to-URA-values |
| **Bounded-retry re-issue discharge** | BUILD in the funnel | new; discharges the "confirming feed does not yet show it" suppression so a genuinely un-applied write is still re-sent (bounded; not never) |
| Coherence classifier `URA_ECHO_MANUAL` / `STALE_MANUAL-by-profile-match` | **DELETE from spec (C20)** | premise refuted; do not build |
| "Trust `hold_activity` universally" corollary from REV 2 | **DELETE from spec (C22)** | premise refuted by physical probe; replaced by the per-brand oracle |

### 1.2 Prior planning docs consulted (headers or bodies)

- `docs/planning/PLANNING_hvac_governed_excursion.md` — rev-6 banner (lease gate stripped; do not
  rebuild) + kinds enum + `return_excursion` bookkeeping-only invariant. BODY skimmed.
- `docs/planning/PLANNING_hvac_excursion_restore_unified.md` — the parked D2/D3/D4 rework (3
  CRITICALs from 2026-08-26 four-review). W1-B RESPECTS the parking: does not rebuild the D2 AST
  governance gate, does not rebuild the D3 manual-preset recovery interlock, does not re-introduce
  the S14 off-phase-ceiling token. Presets-only returns + provenance ownership + REV 3 oracle are
  disjoint — remove the MANUAL by construction rather than by post-hoc governance.
- `docs/planning/PLANNING_hvac_live_room_establishment.md` — Stage-0 SHIPPED v5.103.15; consumers of
  `conditioning_retreat_ok` overlap with S1 preset writes. W1-B does not change that gate.
- `docs/planning/PLANNING_hvac_zone_conditioning_demand.md`,
  `..._d5_reframe_occupancy_gate.md`, `..._demand_knobs_and_observability.md` — HEADERS only;
  downstream consumers of preset flips, not producers.
- `docs/planning/AUDIT_thermostat_write_paths_2026_09_16` — inventory result folded into parent
  card body: `set_preset_mode` 10/10 funnelled, `set_temperature` 11/11 funnelled, `set_hvac_mode`
  now 7/7 funnelled (W1-A Stage A shipped).

### 1.3 Memory bodies pulled

- `feedback_extend_existing_never_rebuild.md`, `feedback_wire_in_anchor_mandatory.md`,
  `feedback_suppression_needs_discharge.md`, `feedback_mutation_verification_pycache_staleness.md`,
  `feedback_no_soak.md`, `feedback_do_robust_fix_not_bandaid_and_card.md`,
  `feedback_tier2plus_prior_art_scan.md`, `feedback_falsify_before_asserting.md`,
  `feedback_hollow_test_anchors.md`, `feedback_coincidental_equality_masks_concept_split.md`
  (this last one now explicitly WHY the coherence classifier failed — the `preset_mode==manual /
  hold_activity==named-preset` coincidence was a happy-path artifact, not the discriminator we
  hoped; C22 shows the mirror coincidence in the §9.7 case).
- `feedback_measure_before_build.md` — the physical-truth probe in §3 IS this discipline; the
  operator's controlled app-change is the hand-built fixture.

### 1.4 Design docs read

- `docs/Coordinator/HVAC_ARCHITECTURE_STATE_OF_PLAY.md` — full read; C16-C22 folded; §9.7 folded
  as the primary REV 3 driving observation.
- `docs/Coordinator/THERMOSTAT_DEFINITION_CARRIER_BRYANT.md` rev 2 — ships D0 of this cycle.
- `docs/readmes/README_v5.103.16.md` — W1-A ledger row shape (values_before/values_after,
  wire_ok, excursion_id) IS the input surface for the D0 probe and the D2.7 oracle.
- `docs/Coordinator/HVAC_COORDINATOR_MANUAL.md` — SKIMMED; superseded by state-of-play in the
  areas this cycle touches.

### 1.5 Code locations surveyed end-to-end

- `custom_components/universal_room_automation/domain_coordinators/hvac_setpoint.py` (funnels, incl.
  new `emit_set_hvac_mode` from W1-A).
- `.../hvac_excursion.py` (`begin_excursion` / `return_excursion`, `_auto_return` :667/:750/:1188,
  boot nudge restore :1131, `auto_release_on_incomplete` :1322, kinds :94-104,
  snapshot :814).
- `.../hvac_override.py:129-262, :2304-2340, :3187-3203, :3447/3816/3934/3969, :3872 (→4113),
  :4008/4043/4113, :4339-4650, :4360/4380, :4683, :4770, :5660, :5814, :5892, :6220-6245`.
- `.../hvac_predict.py:583/889/943/976/1160/1386/1448/1507/1511/1526/1560`.
- `.../hvac_egress.py:621/683/779/795`.
- `.../hvac.py:429/521/1731/2013/2362-2365/2479/2504-2539/2674/2716-2748/3023/3046/3068/5328-5463`.
- `.../hvac_preset.py:202-217`.
- `.../coordinator_diagnostics.py:494-495/554` (display consumer).
- `.../hvac_zones.py:512/714-716` (setpoint read + entry dwell semantics).
- `/Users/okosisi/ha-config/custom_components/ha_carrier/climate.py + const.py +
  carrier_data_update_coordinator.py` (behaviour cited in companion doc; C21 5-min post-write
  local-copy guard).
- `scripts/probes/carrier_feed_truth_probe.py` and `scripts/probes/carrier_feed_truth_episodes.py`
  (C22 methodology + episode-pool results; the D0 probe extends these against W1-A rows).

---

## 2. Non-goals (explicit)

- No coherence classifier (`URA_ECHO_MANUAL` withdrawn).
- No profile-setpoint match classifier (ha_carrier does not expose named-profile setpoints).
- No universal cross-brand "which feed is authoritative" rule — the confirmation oracle is
  per-brand DATA inside each Strategy (§5.D2.7).
- No Nest strategy code.
- No `set_activity_setpoint` adoption for nudges this cycle (see §6 Q1).
- No schedule-boundary guard against the vendor resume race (see §6 Q2).
- No live-guard-wipe defense in URA (integration behaviour; not URA's to solve — but D0 probe
  measures it so we know the cost we accept).
- No enablement of D9 / F2 / F4 (Custom Preset Ranges); this cycle only unblocks by moving
  `_last_emitted_range` ownership.
- No attempt to reconcile the STATUS/CONFIG feeds inside URA (they belong to `ha_carrier`); URA
  only chooses WHICH to trust for confirmation, and how long, per the D2.7 oracle.

---

## 3. D0 — Read-only measurement probe (MANDATORY, blocks design freeze)

Per Measure-Before-Build: the leading strand mechanism (companion doc §9 item 1) is UNVERIFIED
and REV 3 additionally requires the physical-truth probe (C22 method) run against the first
clean day(s) of W1-A `climate_write` rows so URA-caused vs human-caused feed disagreements can
be separated per episode.

**Data sources** (all already exist):
- URA DB: `ac_ramp_events` (nudge start / restore / settled rows), `hvac_excursion_events`,
  `ura_activity_log` (preset_change, preset_change_locked_out, `override_detected`, comfort rows).
- **W1-A `climate_write` durable log (v5.103.16 SHIPPED; ledger row carries `values_before` with
  `preset_mode` AND `hold_activity` read synchronously before every URA write, `values_after`,
  `wire_ok`, `excursion_id`, `site`, `zone_id`, `reason`, `ts_issued`/`ts_returned`).** One clean
  day of rows is a prerequisite; ready at Stage A + ≥24 h.
- HA recorder `home-assistant_v2.db` on the live system: `climate.thermostat_bryant_wifi_studyb_zone_1`,
  `climate.up_hallway_zone_2`, `climate.back_hallway_zone_3` state + attribute history for
  `preset_mode`, `hold_activity`, `temperature`, `target_temp_high`, `target_temp_low`,
  `hvac_mode`, `next_activity_time`; plus blower / RPM / zone-temperature entities used by the
  C22 physical probe.

**Part A — per-episode strand extraction** (for every nudge return AND every non-nudge borrow
return in the window):
1. Identify the return sequence in `climate_write`: what verbs fired, in what order, at what
   times, with what values.
2. For the S7 preset call in each nudge return: did the funnel emit a `resume` first (grep the
   log for the resume kwarg), or a bare pin?
3. At the timestamp of each `set_preset_mode` call, what was `hold_activity` (from
   `values_before`) — was it already `manual` (so `_needs_resume_first` should have fired) or
   something else?
4. When did the observed `manual` appear afterwards, on BOTH `preset_mode` AND `hold_activity`
   feeds (recorder attribute history)? Compute onset lag for each feed.
5. Between the return sequence and the onset, was there any refresh-triggering event visible
   (attribute jump on other zones on the same account = full reconcile signature)?
6. Was another zone / system on the same account written between return and onset — any
   resume/full-refresh trigger from a sibling (C16 wipe candidate)?

**Part B (REV 3) — physical feed-truth probe** (`scripts/probes/carrier_feed_truth_episodes.py`
methodology, extended):
1. For every disagreement between STATUS and CONFIG feeds in the window, form an episode bounded
   by "first disagreement" → "next agreement or next URA write on the entity".
2. For each episode, sample blower state + zone temperature + BOTH feeds' cooling setpoints per
   minute. Apply the 2 °F differential guard (only minutes with a clear thermal signal count as
   "decisive").
3. **Join to W1-A `climate_write` rows on the entity in the same episode** — the row's
   `values_before.preset_mode` + `values_before.hold_activity` classify the episode's leading edge:
   - Preceded by URA write with matching `values_after` and no `override_detected` on the entity
     within the same window -> **URA-CAUSED** disagreement (the §9.1 strand class or the §9.7
     churn class).
   - Preceded by `override_detected` on the entity with `values_before.preset_mode == "manual"`
     AND no matching URA write of those values in the window -> **HUMAN-CAUSED** disagreement
     (the zone_2 00:45 class).
   - Neither -> **UNCLASSIFIED**; report separately.
4. Pool decisive minutes per (disagreement class, cause class) as C22 did (HOLD-followed vs
   STATUS-followed). Output the discrimination table.

**Part C (REV 3, MANDATORY BEFORE DESIGN FREEZE) — operator controlled test:**
- Operator changes zone 2 or zone 3 by hand in the Carrier app at a noted timestamp (the KNOWN
  human case). Record: `(zone, ts, new_preset, new_setpoints)` in a small side file
  `docs/planning/AUDIT_hvac_w1b_operator_controlled_test_2026_09_XX.md`.
- Verify (a) the arrester books `override_detected` with matching `values_before`; (b) the
  W1-A `climate_write` log has no URA write of the same values in the confirmation window;
  (c) Part B classifies this episode HUMAN-CAUSED and the pool assigns it STATUS-followed. If
  (a)/(b)/(c) do not hold, the CarrierStrategy oracle rule stated in §0.1 does NOT hold and
  D2.7 authors the oracle DATA from the probe's discrimination table directly.

**Output shape (per episode + roll-up):**
- Strand table row (Part A): `(zone, return_ts, verbs_in_return, s7_used_resume_first,
  hold_activity_at_pin, onset_lag_status_s, onset_lag_config_s, sibling_write_between,
  refresh_signature)`.
- Feed-truth table row (Part B): `(zone, episode_start, episode_end, disagreement_class,
  cause_class, decisive_minutes_hold_followed, decisive_minutes_status_followed,
  physical_leader)`.
- Roll-up: distribution of onset lag on both feeds; frequency of (a) bare pin over anonymous
  hold, (b) resume-then-pin over anonymous hold, (c) sibling write in the interval, (d) full
  refresh in the interval; PLUS the C22-style pooled decisive-minutes per (disagreement class,
  cause class).
- **Config-combination matrix** built passively from the extraction: for each observed
  combination of (verb order, hold state at pin, sibling activity, refresh coincidence),
  count strand vs no-strand.
- **Confirmation-oracle discrimination table:** per (disagreement class, cause class), the
  authoritative feed (HOLD or STATUS) and the confidence (decisive minutes ratio + n episodes).
  IF a class is present with n≥3 AND the loser gets 0 decisive minutes -> RULE. IF ratio is
  close or n is 1 -> KEEP IT AS A CANDIDATE with the confirmation window widened until either
  the ratio clears or the operator's controlled test seeds another data point.

**Discrimination**:
- If (a) dominates strand cases -> the funnel's resume-decision race is the mechanism; the fix is
  presets-only returns + snapshot correctness (§5.D2).
- If (b) dominates -> the shared-guard wipe (C16) is the mechanism; the fix is what we can do
  from our side is a no-op reclaim rather than defending the pin (URA has no lever inside the
  integration).
- If both are represented -> both fixes needed (still all inside §5.D2 scope).
- If neither -> return to the operator; the mechanism is something we have not enumerated.
- **REV 3 additional:** if Part B/C shows any cause-class where the candidate oracle rule loses
  even one decisive minute to the wrong feed, the oracle DATA is authored from the discrimination
  table directly rather than from the candidate rule.

**Non-negotiable:** the plan does not proceed to build until D0 has run (Parts A + B + C), its
output is folded into the D2 fixture table AND the D2.7 CarrierStrategy oracle DATA.

---

## 4. Deliverable order (rev 3)

1. **D0** — one-shot read-only probe (this section §3; Parts A + B + C).
2. **D1** — generic strategy interface (behaviour-neutral; §5.D1).
3. **D4** — reclaim delay knob + kill switch, module consts (§5.D4).
4. **D5** — fully specified generic default (setpoint-drift human detection; no-preset case;
   return order; §5.D5).
5. **D2** — Carrier strategy: BORROW_ACTIVE gate, presets-only returns per-site migration,
   provenance ownership, no-op suppression, `_last_emitted_range` ownership move, snapshot
   correctness, S10/DPM zone-keyed baseline accessor as its own concept, **and the D2.7
   write-confirmation oracle DATA + bounded-retry discharge** (§5.D2).
6. **D3** — knob-expiry reclaim wiring (TAO / immune-person expiry — Comfort Grace removed,
   see §6 Q7).
7. **Live-validation write-back** into README (state-of-play discipline).
8. **D6 IS FOLDED INTO D2 (per plan review #16).** No separate cleanup pass — each per-site edit
   replaces the site's inline `(setpoints -> preset)` pair with the strategy call in the same
   edit, so the migration cannot half-land.

### 4.1 Why D2.7 is a sub-deliverable of D2, not a stand-alone deliverable

The confirmation oracle is TIGHTLY coupled to the classifier (D2.3) and the funnel no-op
suppression (D2.5): the same `HoldObservation` and the same ProvenanceStore records drive all
three. Splitting the oracle out as its own deliverable would (a) require duplicating the
observation + provenance surface, (b) create a shipping order where a stand-alone oracle
without the classifier or the no-op path is either dead or dangerous, and (c) break the
"each per-site edit replaces the site's inline pair in the SAME edit" invariant that finding
#16 turned into a hard rule for D2. The oracle IS how D2's classifier decides whether an
observed hold "confirms" URA's most-recent write; it is a distinct concept but not a distinct
edit. It lands with D2.

---

## 5. Deliverables

### D0 — Read-only measurement probe

Spec above (§3). Output artifact: `docs/planning/AUDIT_hvac_w1b_strand_mechanism_2026_09_XX.md`
containing the extraction table, roll-up, discrimination verdict, physical-truth pool, and the
confirmation-oracle discrimination table. That artifact IS the input to the D2 fixture table
AND the D2.7 CarrierStrategy oracle DATA.

**Acceptance:**
- **Verify:** the D2 fixture table cites every strand episode in the D0 output as a named test.
- **Verify:** the D2.7 CarrierStrategy oracle DATA cites, for each disagreement×cause class, its
  originating discrimination row (or the candidate rule + widened-window justification if n=1).
- **Verify:** the discrimination verdict is present and folded into the §0 invariant if needed
  (e.g. if C16 wipe dominates, the invariant may relax the "no manual within 10 min" clause and
  strengthen the "URA never books lockout on URA-owned" clause).
- **Verify:** the operator's controlled test entry is in the audit and its episode classifies
  as HUMAN-CAUSED / STATUS-followed.

### D1 — Generic strategy interface (behaviour-neutral)

A stateless module `domain_coordinators/hvac_strategy.py` exposing (finding #13):

```
strategy_for(hass, entity_id) -> Strategy    # cached per BRAND (by registry.platform); never cache fallback
Strategy.observe(hass, entity_id) -> HoldObservation
Strategy.hold_preset(hass, entity_id, preset, *, gate=None, blocking=False, zone_id, reason, site)
Strategy.borrow(hass, entity_id, kind, *, gate, duration, freeze, snapshot, zone_id, reason, site)
Strategy.return_borrow(hass, entity_id, snapshot, *, gate=None, zone_id, reason, site)
Strategy.confirms(observation, intended_write, provenance) -> ConfirmVerdict   # REV 3, D2.7
```

`borrow(...)` accepts EVERY parameter `begin_excursion` accepts today plus `gate`, `duration`,
`freeze` (finding #13; `borrow` is a superset). `hold_preset` inherits the funnel's gate contract.
Every strategy method returns a `WriteResult` (success bool + failed-verb detail) so callers can
implement failed-return retry (finding #10).

`HoldObservation` = `{preset_mode, hold_activity, target_high, target_low, hvac_mode, read_at,
observed_at_source: 'live_state'}`. **No Carrier vocabulary in the interface** (finding #13
constraint) — words like `resume`, `manual`, `hold_activity` only appear inside `CarrierStrategy`.

`ConfirmVerdict` ∈ `{CONFIRMED, UNCONFIRMED, HUMAN_OVERRIDE, INDETERMINATE}` — the funnel maps
these to: skip re-issue / re-issue (bounded retry) / lock URA out / re-issue conservatively.

`Strategy` is a dispatch surface, not per-zone state. Implementations are stateless functions
parameterised by `entity_id`; per-entity runtime state stays where it already lives (prior-art
scan §1.1). The strategy READS/WRITES those existing stores.

**Dispatch rule (finding #12):**
- Look up `entity_id` in HA entity registry (`homeassistant.helpers.entity_registry.async_get`).
- Read `RegistryEntry.platform`.
- Cache the strategy INSTANCE keyed by that platform string (per BRAND, not per entity). Two
  Carrier entities share ONE strategy object.
- On registry miss (transient), return the generic default for THIS call BUT do not cache it.
- Never cache a fallback under a platform key.

**D1 ships behaviour-neutral:** initial method bodies are today's funnel behaviour with strategy
indirection; `confirms()` on the generic default returns `CONFIRMED` iff the observation's
`preset_mode` equals the intended preset (today's implicit behaviour).

**Acceptance:**
- **Test:** `test_strategy_dispatch_by_registry_platform` — Carrier entity -> CarrierStrategy;
  fake platform -> generic default. Discriminating: the fake platform's `hold_preset` MUST NOT
  emit a `resume` even when observation says `hold_activity == "manual"`.
- **Test:** `test_strategy_cache_by_brand` — two distinct Carrier entities return the same
  `CarrierStrategy` instance; a fake-platform entity returns a different instance; a registry
  miss on a Carrier entity returns the generic default without polluting the cache
  (subsequent lookups after the registry recovers must return the CarrierStrategy).
- **Test:** `test_generic_default_confirms_from_preset_mode` — generic default returns CONFIRMED
  iff `observation.preset_mode == intended.preset`; no `hold_activity` inspection.
- **Live:** post-restart, a grep confirms all callers import through `hvac_strategy`; every
  existing behaviour byte-identical (name-diff on the suite).

### D2 — Carrier strategy: presets-only returns, BORROW_ACTIVE gate, provenance, snapshot correctness, confirmation oracle

The load-bearing deliverable. Every site listed in the verified inventory is migrated in the SAME
edit that removes its inline `(setpoints -> preset)` return pair (finding #16).

#### D2.1 BORROW_ACTIVE gate (finding #1, F1)

Derive `BORROW_ACTIVE(entity_id)` = `True` iff:
- a row in `hvac_excursion_state` for this entity is still open (no `ended_at`), OR
- an in-flight nudge for this entity is tracked in `_nudge_pre_preset` / `_override_active`, OR
- a tokenless URA manual writer is currently mid-write on this entity (S9 `hvac_override.py:6221`
  boot ramp audit; S10 `hvac.py:3046` DPM). These get explicit sentinels set at write start,
  cleared at write end.

**Gate at:**
- S1 preset write dispatch (`hvac.py:2674`) — while BORROW_ACTIVE, S1 emits nothing to that entity
  and logs a `preset_write_borrow_gated` row (no `preset_change_locked_out`).
- Arrester override detection (`hvac_override.py:2304-2340`) — while BORROW_ACTIVE, the arrester
  does not book overrides or attempt reverts against that entity.
- Reclaim path (§D2.3) — never fires while BORROW_ACTIVE.

**Per-kind falsifier tests:** for each excursion kind (NUDGE, COMPROMISE, BANKING, PREHEAT,
EGRESS_PAUSE) plus S9 and S10 tokenless writers, a test starts the kind's write, asserts BORROW_ACTIVE
returns True at that entity, mutates the kind's start machinery, asserts the test goes RED.

#### D2.2 Snapshot correctness (finding #2, F3)

Every snapshot-taking site must call `Strategy.observe()` and store a **provenance-aware** view of
`preset_mode`, NOT a raw attribute read. The rule:

- If `observe()` returns a manual observation AND the ProvenanceStore identifies it as URA-owned
  or otherwise not human, the snapshot's `pre_preset` = the STRATEGY'S BEST GUESS of the last
  known named preset for this entity (from `climate_write` last named write, or `state-of-play`
  default for zone, or the most recent house-state's named preset for this zone). Setpoints-only
  return path is used **only** when even that best-guess is unavailable AND the snapshot is a
  genuine human manual.
- If `observe()` returns a genuine human manual, snapshot as manual + current setpoints; return
  via setpoints+preset (the INV carve-out — human manuals are respected).

**Snapshot sites migrated:**
- `hvac_excursion.py:814` (`begin_excursion` snapshot).
- `hvac_override.py:4360/4380` (nudge start / boot audit).
- `hvac_override.py:3872 → 4113` (hard-reset preset assert).
- `hvac_egress.py:621` (egress pause).

Per-site test = mutate the snapshot's `pre_preset` value at that site, assert the corresponding
return test goes RED.

#### D2.3 Provenance ownership (finding #3, F5, F16 — replaces coherence classifier; REV 3 updated to consume the oracle, not the raw feed)

New in-memory helper `ProvenanceStore` (module-level, keyed per entity):

```
ProvenanceStore.record(entity_id, verb, values, wrote_at, snapshot_preset, values_before)
ProvenanceStore.classify(entity_id, observation) -> HoldClassification
ProvenanceStore.clear(entity_id, verb)     # every actual write clears every verb's record for entity
ProvenanceStore.rebuild_on_boot(hass)      # from hvac_excursion_state + W1-A climate_write last row
```

Note `record(...)` now carries `values_before` from W1-A so the classifier can attribute a
zero-delta observation to the URA write that just landed (v5.103.16 ledger).

`HoldClassification` ∈ `{NAMED_HOLD, URA_OWNED_MANUAL, HUMAN_MANUAL, NO_HOLD}` (no
`URA_ECHO_MANUAL`, no `STALE_MANUAL_BY_PROFILE_MATCH`).

**Classification (REV 3 — the classifier consults `Strategy.confirms()` / D2.7 for the
disagreement classes; it does NOT hard-code trust in either feed):**
- `observation.preset_mode != "manual"` AND `Strategy.confirms(observation, last_write, prov)`
  returns `CONFIRMED` -> `NAMED_HOLD` or `NO_HOLD`.
- `observation.preset_mode != "manual"` AND `Strategy.confirms()` returns `UNCONFIRMED` (the
  §9.7 case: STATUS names a preset the CarrierStrategy oracle rejects as un-followed by the
  device) -> classify per URA's last write; the reclaim/re-issue path is gated by the
  bounded-retry discharge (§D2.5).
- `observation.preset_mode == "manual"`:
  - `Strategy.confirms(observation, last_write, prov)` returns `HUMAN_OVERRIDE` (there is an
    `override_detected` row within the confirmation window whose `values_before.preset_mode ==
    "manual"` was not preceded by a URA write of those values) -> `HUMAN_MANUAL`.
  - Otherwise if URA has an in-window `set_temperature` record for this entity whose values
    match `observation.target_low/high` AND no URA `set_preset_mode(named)` has fired since
    -> `URA_OWNED_MANUAL`.
  - else -> `HUMAN_MANUAL`. **NOTE:** a manual observation AFTER a URA NAMED write with a
    matching `override_detected` row is always HUMAN (F9 + REV 3 zone_2 00:45 case).

**Window model (finding #7, F9 — CLASSIFICATION-ONLY, never blanket suppression):**

The window is the shape of "URA's write can still be represented as URA-owned" — it starts at
dispatch of the URA write, is extended on completion, and ends at
`max(last_write_ts + POST_WRITE_INTERCEPT_S, last_write_ts + PRESET_TTL_S)` OR on a matching
observation OR on a URA named-preset write (which clears the temperature-write record for that
entity), whichever comes first.

`resume → pin` counts as ONE LOGICAL WRITE (window starts at resume dispatch, ends at pin completion).

**Kept / retired window table:**
| Constant | Verdict | Rung | Rationale |
|---|---|---|---|
| `SUPPRESS_TTL_SECONDS = 5` (temp writes) | KEEP | 1 | Deliberately short so human at dial is seen (`hvac_override.py:141-146`) |
| `SUPPRESS_TTL_SECONDS_PRESET = 120` (preset writes) | **RETIRE** (finding #7) | — | Superseded by ProvenanceStore's provenance-aware classification; no blanket suppression needed |
| `POST_WRITE_INTERCEPT_S = 300` (matches `ha_carrier` `POST_WRITE_INTERCEPT_WINDOW_MINUTES = 5`) | NEW, module const | 1 | Protocol constant (companion doc §5); review-only |
| `PRESET_TTL_S = 120` (upper bound of preset-window classification) | NEW, module const | 1 | Ceiling for `URA_OWNED_MANUAL` after a preset write clears prior temp write |
| `CONFIRMATION_WINDOW_S = 300` (REV 3, D2.7) | NEW, module const | 1 | Time after a URA write in which the confirming feed must show the intended value for `CONFIRMED`; else `UNCONFIRMED` (bounded retry) |
| `CONFIRMATION_RETRY_MAX = 2` (REV 3, D2.7) | NEW, module const | 1 | Bounded retry cap for `UNCONFIRMED` re-issue; after cap, emit NM `[CONFIRMATION EXHAUSTED]` and stop re-issuing |
| `CONFIRMATION_RETRY_BACKOFF_S = 60` (REV 3, D2.7) | NEW, module const | 1 | Minimum spacing between bounded retries on the same intended value |
| `NAMED_PROFILE_MATCH_TOLERANCE_F` (rev-1) | **DELETE** | — | Killed by C20 / F5 (profile setpoints not queryable) |

**Restart rebuild (finding #9):** on integration setup, `ProvenanceStore.rebuild_on_boot`:
1. Loads still-open `hvac_excursion_state` rows -> re-populates in-flight nudge / borrow state.
2. Loads the LAST `climate_write` row per entity (verb, values, wrote_at, values_before) from
   W1-A durable log.
3. If the last row is a temperature write within `POST_WRITE_INTERCEPT_S` of boot, record it as
   an active provenance record. Older records classify as expired.

If the store is empty on boot (e.g. W1-A log unavailable), classification errs toward
`HUMAN_MANUAL` -> URA locks itself out (safe direction). A logged NM entry surfaces the
"provenance store empty on boot" condition once.

#### D2.4 Presets-only borrow return per verified inventory (F7)

**Verified return-sequence inventory (10 sequences; each migrated in the SAME edit that removes the
inline pair, finding #16):**

| # | Site | File | Kind |
|---|---|---|---|
| 1 | Nudge restore (S6 setpoints + S7 preset) | `hvac_override.py:4595, :4640` | NUDGE |
| 2 | Nudge cancel (S8) | `hvac_override.py:5814-5841` | NUDGE (button) |
| 3 | Boot ramp audit restore (S9) | `hvac_override.py:6220-6245` | NUDGE (boot audit) |
| 4 | S4 arrester revert | `hvac_override.py:3519/3547` | COMPROMISE revert |
| 5 | Hard reset restore | `hvac_override.py:4008, :4043, :4113` | HARD_RESET (into INV) |
| 6 | Auto-return (excursion lease expiry) | `hvac_excursion.py:667` | NUDGE-excluded kinds |
| 7 | Auto-return (sweep) | `hvac_excursion.py:750` | any |
| 8 | Auto-return (banking release) | `hvac_excursion.py:1188` | BANKING |
| 9 | Boot nudge restore | `hvac_excursion.py:1131` | NUDGE (boot) |
| 10 | Auto-release-on-incomplete (partial-write) | `hvac_excursion.py:1322` | any |

Plus these NON-return borrow-adjacent sites that ALSO route through the strategy for consistency:
- Banking release (S11): `hvac_predict.py:979/1040`.
- Pre-cool (S12): `hvac_predict.py:1160`.
- Pre-heat (S13): `hvac_predict.py:1448/1511/1560`.
- Egress pause/resume: `hvac_egress.py:683/779/795`.

**Return contract per site:**
1. Compute return via `Strategy.return_borrow(entity_id, snapshot, ...)`.
2. Order (finding #15): **mode → preset → (setpoints only if strategy says no presets available)**.
3. If snapshot's `pre_preset` is a NAMED profile -> presets-only path (no preceding setpoints).
4. If snapshot is a genuine `HUMAN_MANUAL` -> setpoints+preset fallback with the human's values.
5. On failed return (`WriteResult.ok=False`): finding #10 retry — up to 1 retry with discharge
   (delay), pass the site's `gate` through so a comfort-delay veto is honored; on second failure,
   emit the `[GOVERNED BORROW RESTORE FAILED]` NM latch and leave the excursion row open for
   sweep pickup.
6. Site still calls `return_excursion` for bookkeeping only.

**Per-site service-call-count test (finding #16):** for each of the 10 sites, a test drives the
site's return path with a named-preset snapshot and asserts:
- Exactly ONE `climate.set_preset_mode` call fires.
- ZERO `climate.set_temperature` calls fire.
- ZERO redundant `resume` calls unless `hold_activity == "manual"` at pin time.

For a `HUMAN_MANUAL` snapshot, the counts are: ONE `climate.set_temperature`, ONE
`climate.set_preset_mode`. Discriminating: swap the snapshot classifier's verdict; the counts must
flip.

**Per-site source-mutation test (Reviewer C):** for each of the 10 sites, edit the production
source at that site to bypass the strategy call and confirm a SPECIFIC test fails; restore.

#### D2.5 No-op write suppression at the funnel (finding #5; REV 3 extended)

- Suppress iff (a) intended `(verb, values)` equal the funnel's last-sent record for this entity
  AND (b) the observed state equals those values.
- **REV 3 addition (the §9.7 fix):** additionally suppress iff `Strategy.confirms(observation,
  intended_write, provenance)` returns `CONFIRMED` for the intended `(verb, values)` — i.e. the
  confirming feed (per the brand's D2.7 oracle DATA) already shows the intended preset, even if
  the OTHER feed disagrees. This is what stops URA re-writing AWAY on §9.7 when the CONFIG feed
  already reads away.
- **REV 3 discharge (a suppression MUST have a discharge — `feedback_suppression_needs_discharge`):**
  if `confirms()` returns `UNCONFIRMED` (the confirming feed does NOT show the intended value
  within `CONFIRMATION_WINDOW_S`), the funnel re-issues on a bounded retry — up to
  `CONFIRMATION_RETRY_MAX` retries spaced by `CONFIRMATION_RETRY_BACKOFF_S`, after which the
  funnel emits `[CONFIRMATION EXHAUSTED]` NM latch AND stops re-issuing (so a truly stuck
  integration does not turn into a write storm). BORROW_ACTIVE gates apply. Restart-safe: the
  retry counter is per (entity, intended-value) in-memory, rebuilt from W1-A last write row on
  boot.
- Any actual write to the entity clears EVERY verb's last-write record for that entity.
- Observed divergence from the last-write record clears that record.
- Re-asserts and reclaims are exempt from (a)/(b) BUT still consult `confirms()` (they must fire
  even when values match, EXCEPT when the confirming feed already shows the desired value —
  otherwise a re-assert defeats itself into the §9.7 churn).

**Symmetric guard for the HUMAN case (REV 3, from INV-W1B conjunct 4):** if `Strategy.confirms()`
returns `HUMAN_OVERRIDE` at the time of an intended URA write to the same entity, the funnel
BLOCKS the write and books the S1 lockout as normal. The HUMAN_OVERRIDE verdict comes from D2.7
joining the arrester's `override_detected` row to the confirmation window (see §5.D2.7).

#### D2.5a S10 / DPM zone-keyed baseline accessor as its OWN concept (finding #5, F8)

The `_last_emitted_range` state at `hvac.py:521` is doing TWO jobs today:
1. Funnel-level no-op-write suppression (D2.5).
2. S10/DPM zone-keyed comfort baseline (`hvac_predict.py:889/943/1526`; readers/writers at
   `hvac.py:429/521/3023/3068`).

Split them:
- `Funnel.last_sent[entity_id][verb]` — the no-op-write suppression record (D2.5), NEW inside the
  strategy funnel.
- `HvacZoneBaseline[zone_id]` — the S10/DPM zone-keyed comfort baseline, MOVES to its own tiny
  helper module preserving the exact reader/writer semantics of the existing state.
  **F8 exemption:** the S10 baseline writer is exempt from ProvenanceStore reclaim — its
  writes are baseline-recomputes, not overrides, and reclaiming against them would flap.

#### D2.6 S1 + arrester + consumer wiring (finding #17, F4)

**S1 wiring (correct per finding #17):**
- `should_change_preset` (`hvac_preset.py:212-217`) reads `Strategy.classify(...)` — the manual
  refusal now branches on `HUMAN_MANUAL` only. `URA_OWNED_MANUAL` returns "OK to change"
  (reclaim), respecting BORROW_ACTIVE.
- Lockout discharge (`hvac.py:2479`) fires on any classification transition to `NAMED_HOLD` or
  `NO_HOLD`.
- Lockout ledger row (`hvac.py:2509`) is written only for `HUMAN_MANUAL` refusals.

**Consumer table (F4) — every reader of `preset_mode`, with trust vs display column:**

| Consumer | File:line | Role | Uses Strategy.observe()? |
|---|---|---|---|
| S1 preset dispatch | `hvac.py:2013, :2674` | trust | YES via `should_change_preset` |
| Arrester override detect | `hvac_override.py:2304-2340` | trust | YES |
| Arrester diagnostics | `hvac_override.py:2056, :2451-2453, :2978-2991, :4683, :4770, :5660, :5892` | mixed | YES for trust, raw allowed for display strings |
| Retreat-decision helpers | `hvac_zones.py:512` | trust | YES |
| Diagnostics attrs | `coordinator_diagnostics.py:494-495, :554` | display | RAW allowed (display only) |
| Every other `preset_mode` attribute read | (grep) | (case-by-case) | grep-gated by C3 test below |

**C3 grep test:** a test greps the codebase for `.attributes["preset_mode"]` and
`.attributes.get("preset_mode")` reads and asserts each match either (a) sits inside
`Strategy.observe()` implementation OR (b) is annotated as a display-only site with a
`# preset_mode: display-only` comment on the line. The test name is `observed_hold` per finding
#17. Any new raw read is a build failure.

#### D2.7 Write-confirmation oracle DATA (REV 3, new — the load-bearing REV 3 addition)

**Purpose.** Answer, per-brand, the operational question a URA write asks 5 min later: "did my
write take, and if not, do I re-issue?" — WITHOUT hard-coding trust in either Carrier feed.

**Placement.** Per-brand DATA on each `Strategy` implementation, keyed by the disagreement class
of the observation. Sits INSIDE `CarrierStrategy.confirms(...)`; the generic default has the
trivial oracle (`CONFIRMED` iff `observation.preset_mode == intended.preset`). No knob is exposed
to operators — this is a definitional constant table per brand, Rung 1 (module const,
review-only).

**Inputs (existing surfaces, REV 3 joins them):**
1. `HoldObservation` from `Strategy.observe()` (the two Carrier feeds, `hvac_mode`, setpoints).
2. `IntendedWrite` from the funnel = `(verb, values, ts_issued, entity_id, site, reason)`.
3. `ProvenanceStore.last_write_for(entity_id)` — the just-before record from D2.3 (which now
   includes W1-A `values_before` per §D2.3 update).
4. `arrester.human_override_within(entity_id, window)` -> Optional[OverrideDetectedRow] — the
   arrester's `override_detected` row within `CONFIRMATION_WINDOW_S`. Filters to rows whose
   `values_before.preset_mode == "manual"` was NOT preceded by a URA write of the same values
   in the window (i.e. genuine human) — this is the existing arrester detector reused, with the
   REV 3 join to W1-A `values_before` to catch zero-delta human dial-back-to-URA-values.

**Verdicts:**
- `CONFIRMED` — the brand's oracle DATA classifies the observation as consistent with the
  intended write. Funnel suppresses re-issue (§D2.5); classifier maps to `NAMED_HOLD`/`NO_HOLD`.
- `UNCONFIRMED` — the brand's oracle DATA classifies the observation as NOT showing the intended
  write yet, WITHIN the `CONFIRMATION_WINDOW_S`. Funnel triggers bounded retry (§D2.5).
- `HUMAN_OVERRIDE` — a genuine human override is detected on this entity within the confirmation
  window. Funnel BLOCKS a URA write to that entity and books S1 lockout as normal.
- `INDETERMINATE` — the observation's disagreement class is not covered by the oracle DATA
  (D0 discrimination did not seat it). Funnel behaves as REV 2 today (re-issue on schedule; no
  aggressive suppression) AND emits a one-shot NM `[ORACLE INDETERMINATE]` with the observation
  so the operator can extend the DATA in a subsequent cycle. This is the safe default; it
  degrades to REV 2 behaviour, never worse.

**CarrierStrategy oracle DATA — authored from D0 discrimination table.** Candidate seed (subject
to D0 confirming; UNPROVEN at n=1 per case):

| Disagreement class | Cause class | Confirming feed | Verdict shape |
|---|---|---|---|
| Named vs named (`preset_mode` names A, `hold_activity` names B) | any | `hold_activity` | CONFIRMED iff `hold_activity == intended.preset`; else UNCONFIRMED (§9.7 case) |
| Status=`manual`, hold names X | HUMAN-CAUSED (`override_detected` matched) | `preset_mode` | HUMAN_OVERRIDE (funnel blocks) |
| Status=`manual`, hold names X | URA-CAUSED (URA write within window with matching values, no override_detected) | `hold_activity` | CONFIRMED iff `hold_activity == intended.preset` (the §9.1 strand class: hold X leads) |
| Both feeds agree (named or manual) | any | (either) | CONFIRMED iff both == intended; else UNCONFIRMED |
| Anything else | any | — | INDETERMINATE + NM one-shot |

**Bounded-retry discharge (from §D2.5, restated for the oracle):** an `UNCONFIRMED` verdict
triggers up to `CONFIRMATION_RETRY_MAX` re-issues spaced by `CONFIRMATION_RETRY_BACKOFF_S`. After
the cap, emit `[CONFIRMATION EXHAUSTED]` NM AND stop re-issuing on this intended value — a
genuinely un-applied preset is loud, not silent, and does not spiral into a write storm.

**BORROW_ACTIVE interaction:** while BORROW_ACTIVE for an entity, the oracle is not consulted
(S1 and the arrester write nothing per D2.1). On borrow return, the return write itself is the
next "intended write" and its `confirms()` starts a fresh window.

**Restart:** on boot, the oracle's per-entity retry counter is empty; the FIRST tick after boot
reads the observation fresh and either CONFIRMS (nothing to do) or UNCONFIRMS (starts a new
bounded retry from 0). No stale retry state can survive a restart.

**Acceptance for D2.7:**
- **Test:** `test_oracle_named_vs_named_disagreement_confirms_from_hold` (§9.7 fixture from
  recorder + climate_write): STATUS=home, HOLD=away, intended.preset=away -> CONFIRMED; no
  re-issue.
- **Test:** `test_oracle_named_vs_named_disagreement_unconfirms_when_hold_disagrees`: STATUS=home,
  HOLD=home, intended.preset=away -> UNCONFIRMED; bounded retry fires; after
  `CONFIRMATION_RETRY_MAX`, `[CONFIRMATION EXHAUSTED]` NM emitted and re-issue stops.
- **Test:** `test_oracle_human_override_blocks_ura_write` (zone_2 00:45 fixture): STATUS=manual,
  HOLD=sleep, `override_detected` present, no prior URA write of matching values -> HUMAN_OVERRIDE;
  funnel blocks the URA write; S1 books lockout.
- **Test:** `test_oracle_ura_owned_manual_after_borrow_confirms_from_hold` (§9.1 strand fixture):
  STATUS=manual, HOLD=home, URA write of home present within window, no override_detected ->
  CONFIRMED for intended.preset=home (the §9.1 strand class); classifier maps to URA_OWNED_MANUAL
  for reclaim path.
- **Test:** `test_oracle_indeterminate_falls_back_to_rev2_behaviour_with_nm`: an observation whose
  disagreement class is NOT in the DATA table -> INDETERMINATE; funnel behaves as REV 2; one-shot
  NM emitted.
- **Test:** `test_oracle_bounded_retry_restart_safe` — retry counter is per (entity, intended-value)
  and empty on boot; first post-boot observation starts fresh.
- **Test (mutation-anchored):** for each of the 5 verdict rows in the DATA table, mutate the row
  to swap the confirming feed and confirm a SPECIFIC named test fails; restore.
- **Live (state-of-play discipline):** post-restart on the §9.7 zone_1 case, `climate_write`
  re-issue rate for `away` on zone_1 falls to ~0 from the ~6/h pre-fix rate, measured over a
  72-h window; AND zero `climate_write` rows overwrite an `override_detected` row on any zone
  in the same window (see §7 ship gate).

**Acceptance for D2 (integrated):**
- **Verify:** service-call-count tests pass for all 10 return sequences (§D2.4).
- **Verify:** BORROW_ACTIVE per-kind falsifier tests pass (§D2.1).
- **Verify:** ProvenanceStore restart-safe test passes (§D2.3).
- **Verify:** oracle DATA tests pass (§D2.7).
- **Verify:** `_corrective_writes_suppressed` + active comfort grant gate the reclaim path (F6);
  discriminating tests.
- **Sensor:** `ura_activity_log` row `preset_change_locked_out` count drops materially per zone.
- **Sensor:** `ura_activity_log` `climate_write` re-issue rate on the §9.7 zone_1 case falls to
  ~0 over the disposition window.
- **Test:** `test_carrier_return_presets_only[all 10 sites]` (mutation-anchored).
- **Test:** `test_provenance_classify_matrix` — matrix built from D0's config-combination table.
- **Test:** `test_no_op_write_suppression_at_funnel` — repeat write with identical values +
  matching observation emits zero service calls; observed divergence clears the record and next
  write fires.
- **Test:** `test_zone_baseline_split_semantics` — S10/DPM baseline reads and writes match the
  pre-migration behaviour byte-for-byte.
- **Test:** `test_hold_activity_after_named_write_is_always_human` (F9 corollary; REV 3 refines:
  only when the arrester books `override_detected` and it is not URA-echo).
- **Test:** `test_borrow_active_gates_s1_and_arrester` (mutation-anchored per BORROW_ACTIVE
  source).
- **Live:** post-restart, D0's config-combination matrix REPLAYS as a fixture against the
  strategy in the test suite AND the ship gate query on the running instance shows zero
  falsifying episodes over the 72 h window (see §7).

### D3 — Knob-expiry reclaim wiring (finding #8, F6, Q7 DECIDED — operator decision 7)

Per operator challenge 2026-09-25 ("we have a knob that says don't override till next change, and
that knob times out"): TAO and immune-person hold expire against a hold that today does not get
released.

D3 wires each expiring knob to a strategy-level release:
- On expiry, if `Strategy.classify()` returns `URA_OWNED_MANUAL` -> `hold_preset(snapshot.pre_preset)`.
- On expiry, if `Strategy.classify()` returns `HUMAN_MANUAL` -> **reclaim to S1's current target** (today's
  house-state preset, NOT the snapshot) — binding operator decision 7 (2026-09-26).
- BORROW_ACTIVE gates every reclaim.
- `_corrective_writes_suppressed` and active comfort grant gate every reclaim (F6).
- **Comfort Grace REMOVED from D3** (finding #8): its grant expiry is not the right release
  channel (it wrote nothing today, and adding a write there conflates comfort with reclaim).
- Reclaim writes are subject to §D2.5 no-op suppression + the D2.7 oracle: a reclaim that would
  re-issue a preset the confirming feed already shows is skipped.

**Acceptance:**
- **Test:** `test_tao_expiry_reclaims_ura_owned_manual` — TAO expires with a URA-owned manual
  present; exactly one `hold_preset(snapshot.pre_preset)` fires; BORROW_ACTIVE-gate discriminating
  test (no fire while a borrow is live).
- **Test:** `test_immune_person_expiry_reclaims_ura_owned_manual` — same shape, different knob.
- **Test:** `test_comfort_grace_does_not_reclaim` — Comfort Grace expiry emits nothing (removed).
- **Test:** `test_tao_expiry_reclaims_human_manual_to_s1_current_target` — HUMAN manual present at expiry; the reclaim writes S1's current target (not the snapshot pre_preset); discriminating vs the URA-owned branch.
- **Live:** post-restart, the four historical strand cases in §9.1 replay against the strategy
  as fixtures and clear within one tick after the earliest matching knob expiry.

### D4 — Reclaim knob = DELAY before URA-owned reclaim + separate kill switch (finding #4)

The rev-1 "reclaim window in minutes" is REPLACED by:

**Rung 3 (Number entity) — `number.ura_hvac_coordinator_ura_owned_manual_reclaim_delay_s`:**
DELAY between BORROW_ACTIVE releasing and the reclaim firing on a URA-owned manual with no borrow
active. Default = **1 tick** (or "0 s = same-tick"). RestoreEntity, live-tunable.

**Rung 3 (Switch entity) — `switch.ura_hvac_coordinator_ura_owned_manual_reclaim_enabled`:**
Separate KILL SWITCH (finding #4). Default ON. When OFF, no reclaim fires regardless of delay.
Distinguishes "off" from "very delayed".

**Rung 1 (module const) — `POST_WRITE_INTERCEPT_S = 300`:** see §D2.3 table.
**Rung 1 (module const) — `PRESET_TTL_S = 120`:** see §D2.3 table.
**Rung 1 (module const, REV 3) — `CONFIRMATION_WINDOW_S = 300`, `CONFIRMATION_RETRY_MAX = 2`,
`CONFIRMATION_RETRY_BACKOFF_S = 60`:** see §D2.3 table + §D2.7.

**Acceptance:**
- **Verify:** kill switch OFF blocks reclaim; delay=0 fires next tick; delay=120 fires after 2
  ticks; discriminating test (not the same as "off").
- **Live:** entities exist post-restart with defaults.

### D5 — Fully specified generic default (finding #14)

For any thermostat NOT `ha_carrier`:

- `hold_preset` = direct pin (no `resume` — that is Carrier-vocabulary; a generic default may not
  emit it).
- `borrow` = optimistic snapshot from `observe()`; use `set_temperature` + `set_preset_mode`.
- `return_borrow` order (finding #15): **mode -> preset -> setpoints only if the entity advertises
  NO `preset_modes`.**
- `observe()` reads standard climate attributes; `hold_activity` may be `None` — the classifier
  treats absent hold as `NO_HOLD` and never emits URA-owned inferences over an entity without
  writable presets.
- `classify()` uses provenance-only:
  - If ProvenanceStore has a matching in-window `set_temperature` record whose values equal
    `observation.target_high/low` AND the observation's `preset_mode` is `None` or the "manual"-
    equivalent for that thermostat -> `URA_OWNED_MANUAL`.
  - **Setpoint-drift human detection:** if the observation's setpoints CHANGE with no URA write
    record in the interval, classify as `HUMAN_MANUAL`.
- **No-preset thermostats:** `hold_preset` returns a `WriteResult.ok=False` with reason
  `no_presets_supported`; caller uses `set_temperature` fallback. `return_borrow` on such an
  entity uses setpoints-only path.
- `confirms()` (REV 3): trivial oracle — `CONFIRMED` iff `observation.preset_mode ==
  intended.preset`; `INDETERMINATE` otherwise (the generic default MUST NOT claim per-feed
  authority it has not tested).

**Acceptance:**
- **Test:** `test_generic_default_no_resume_emitted` — stub non-Carrier entity gets a direct pin
  even when `hold_activity == "manual"`.
- **Test:** `test_generic_default_setpoint_drift_is_human` — observation setpoints change with no
  ProvenanceStore record; classify returns `HUMAN_MANUAL`.
- **Test:** `test_generic_default_no_presets_fallback` — entity without `preset_modes` gets
  setpoints-only return path.
- **Test:** `test_generic_default_confirms_trivially` — confirms only when `preset_mode` matches;
  INDETERMINATE otherwise.
- **Non-goal:** no Nest strategy code. Interface accepts one.

---

## 6. Operator questions

> **Q1–Q7 are RESOLVED by the binding operator decisions at the end of this file (2026-09-26, "Accept recs"): Q1→decision 1 (no `set_activity_setpoint`), Q2→decision 2 (no schedule-boundary guard; operator reduces schedules), Q3→decision 3 (DELAY = 1 tick + separate kill switch), Q4→decision 4 (N≥10 per zone, 10-min window), Q5→decision 5 (no Nest stub), Q6→decision 6 (Rung-1 module constants — extends to the REV 3 CONFIRMATION_* constants), Q7→decision 7 (reclaim the HUMAN hold to S1's current target). Only Q8 and Q9 are open.** (Orchestrator correction 2026-09-26 — REV 3 draft left Q3/Q7 reading as open.)

1. **`set_activity_setpoint` as a no-hold nudge path.** §3 companion. Adopt in W1-B or defer?
   Recommendation: **KEEP nudges on `set_temperature` this cycle** — the interrupted-edit ingredient
   introduces a permanent-profile-mutation risk we do not need to buy today given the presets-only
   returns fix the strand.
2. **Bryant schedule scope.** Zones 2/3 still run 4-entry schedules. Depend on further schedule
   reduction, or add a schedule-boundary guard against the resume-vs-vendor race? Recommendation:
   **operator continues schedule reduction; no schedule-boundary guard in W1-B.**
3. **Reclaim DELAY default.** Rev-1's "30 min window" is REPLACED by rev-2's DELAY (§D4). Default
   1 tick (same-tick eligible), separate kill switch. Operator agree, or prefer a longer default
   (e.g. 30 s) to observe the strand form itself before URA reclaims?
4. **Ship gate exercised-episode floor N≥10, falsifier threshold 10 min.** Operator willing to
   hold the ship verdict until at least 10 exercised non-nudge return episodes have accumulated
   in the post-deploy window? (Nudges accumulate faster; N is per-zone.)
5. **Nest interface stub.** Skip entirely, or land a `NestStrategy` placeholder that raises at
   construction? Recommendation: **skip.**
6. **`POST_WRITE_INTERCEPT_S` / `PRESET_TTL_S` / (REV 3) `CONFIRMATION_WINDOW_S` /
   `CONFIRMATION_RETRY_MAX` / `CONFIRMATION_RETRY_BACKOFF_S` rung placement.** Proposed Rung 1
   (module const, review-only). Operator agree, or Rung 3?
7. **On TAO / immune-person expiry against a HUMAN hold: reclaim to S1's current target (today's
   house-state preset), or leave the human hold alone?** Finding #8. This is a comfort-vs-respect
   trade — reclaiming means the human's dial-set temperature is overwritten when their protection
   expires, at whatever URA thinks is currently right; leaving means the hold stays until the next
   forced-away write. Recommendation: **reclaim to S1's current target** — that is what "expiring
   the immunity" means in plain English; the immunity was the reason to leave it alone, and its
   expiry is the operator's own signal that the immunity is done. But this is genuinely an
   operator call.
8. **(REV 3, new) Controlled test scheduling.** D0 Part C requires the operator to change zone 2
   or zone 3 by hand in the Carrier app at a noted time, once, before design freeze. When can
   this be scheduled? (5 min operator time; the audit script tags the timestamp.)
9. **(REV 3, new) `[CONFIRMATION EXHAUSTED]` NM latch — should it also demote the affected preset
   target (fall back to a safer preset, e.g. `home`) until the operator ACKs, or purely inform?**
   Recommendation: **purely inform.** Demotion is a second policy that can silently mask a bug;
   the loud NM is the right first response. Operator may override.

---

## 7. Ship gate — disposition query, not soak (finding #11)

**Pre-deploy gate — replay:** after D0 output is folded into the D2 fixture table AND the D2.7
oracle DATA, run the D2 matrix against the strategy code in test. If the replay produces any
strand-equivalent (URA-owned manual + lockout ledger row), OR any oracle DATA row's mutation
does not produce a specific test failure, OR the controlled-test episode does NOT classify as
HUMAN-CAUSED / STATUS-followed, deploy is BLOCKED.

**Post-deploy gate — disposition query at day 3 (or first N≥10):**
- Exercised-episode floor: at least **N=10 non-nudge return episodes per zone** in the post-deploy
  window (nudges will exceed this; non-nudge borrows are the rarer, more expensive case).
- Falsifier threshold (§9.1 case): **10 min** — any strand-equivalent episode within 10 min of a
  URA return fails the gate.
- **REV 3 additional (§9.7 case):** `climate_write` re-issue rate for `away` on zone_1 (and any
  zone matching the named-vs-named disagreement class) must fall to ~0 over the disposition
  window (from the pre-fix ~6/h baseline). Any zone with re-issue rate > 0.5/h fails the gate.
- **REV 3 additional (symmetric human case):** zero `climate_write` rows against any zone within
  the confirmation window of an `override_detected` row whose `values_before.preset_mode ==
  "manual"` was not preceded by a URA write of the same values (i.e. the funnel HUMAN_OVERRIDE
  block held). Any hit fails the gate.
- **REV 3 additional (oracle sanity):** zero `[CONFIRMATION EXHAUSTED]` NM latches OR each latch
  is triaged into either a bug (fix-forward) or a new oracle DATA row (extend + re-deploy).
- Query = one SQL against `ura_activity_log` + `hvac_excursion_events` + W1-A `climate_write` at
  disposition time. NOT a calendar watch (per No-Soak).
- If gate PASSES: dispose the card.
- If gate FAILS with an unmet floor: extend the window until N is met OR the falsifier fires.
- If gate FAILS with a falsifier fire: reopen, analyse the failing episode, plan a
  fix-forward or roll back.

---

## 8. Review protocol (Tier 3 — 4 framing-disjoint reviews + orchestrator hand-check + operator checkpoint)

Per CLAUDE.md Tier 3 + operator standing policy.

- **Reviewer A — local correctness.** Strategy branch logic; ProvenanceStore classify matrix;
  presets-only return per site; per-site edit correctness; REV 3 additionally: `Strategy.confirms()`
  branch arithmetic per DATA row; the bounded-retry counter arithmetic + backoff spacing; oracle
  DATA table cells vs D0 discrimination table (each cell cites its D0 source).
- **Reviewer B — integration / state-machine integrity.** Window discharge (every start has an
  end); BORROW_ACTIVE gate coverage (S1 + arrester + reclaim); restart rebuild correctness; no
  regression on `HUMAN_MANUAL` lockout; no interaction with parked D2/D3/D4 governance;
  shared-account guard wipe consequences documented; failed-return retry with discharge and
  gate pass-through; REV 3 additionally: bounded-retry discharge across restart (retry counter
  reset semantics); the confirmation window's interaction with the C21 5-min ha_carrier local
  guard; oracle+S1+arrester ordering (a HUMAN_OVERRIDE verdict must fire BEFORE any URA re-issue
  in the same tick).
- **Reviewer C — test authority via REAL per-site source mutation.** Each of the 10 return sites
  gets its own mutation; global monkeypatch is NOT sufficient. Bytecode disabled + `__pycache__`
  cleared each drill. Independent re-derivation of the site list — this doc's inventory is a
  hypothesis, not a spec. REV 3 additionally: each of the 5 oracle DATA rows is source-mutated
  (swap the confirming feed) and MUST produce a specific named test failure; also mutate the
  bounded-retry cap and confirm the retry-storm-prevented test fails.
- **Reviewer D — adversarial completeness / diff-blind.** Restate INV-W1B (REV 3 — five conjuncts)
  in reviewer's own words; re-enumerate the ENTIRE thermostat-write surface across `hvac*.py` —
  INCLUDING pre-existing code, not just the diff — for any missed borrow-return site, any writer
  that bypasses the strategy, any classifier consumer that reads `preset_mode` raw without going
  through `observe()`. D also enumerates the shared-account guard wipe triggers, confirms the
  invariant's carve-outs are complete, AND REV 3: re-enumerates every disagreement class the
  Carrier feeds can present (name × name, name × manual, manual × name, manual × manual, plus
  None variants) and confirms each has EITHER an oracle DATA row OR the INDETERMINATE fallback
  path. Any disagreement class the oracle claims to handle without a D0 discrimination row is a
  finding.

**Two plan reviews (this document, before build dispatch — REV 3 mandate):** completeness and
adversarial-build-prediction, both retargeted at REV 3.

- **Plan Reviewer 1 — oracle completeness.** Re-enumerate every disagreement class the Carrier
  feeds can produce (from ha_carrier `climate.py`, not from this doc) and confirm each is
  represented in the D2.7 oracle DATA table OR explicitly routed to INDETERMINATE with a rationale.
  Verify the D0 Part B/C spec actually seats each cell of the oracle DATA (n≥1 with the
  candidate-rule caveat, n≥3 for a hard rule). Verify INV-W1B's five conjuncts are individually
  falsifiable (there IS an observation that would disprove each) and that each has a matching
  ship-gate query row in §7. Verify the bounded-retry discharge cannot degenerate into a write
  storm (cap + backoff + NM latch + restart-safety all present). Re-run the prior-art scan on
  the REV 3 additions (arrester `override_detected`, W1-A `values_before`) and confirm REUSE
  citations at file:line.
- **Plan Reviewer 2 — adversarial build-prediction.** Predict what a builder will get wrong
  reading REV 3: does the plan clearly say the oracle DATA is authored FROM D0 (not from the
  candidate rule verbatim, when D0 disagrees)? Does it clearly say `confirms()` is consulted
  BEFORE any re-issue, INCLUDING at the funnel entry (not only inside the classifier)? Does it
  clearly say the retry counter is per (entity, intended-value) and reset on any actual state
  change or restart? Does it clearly say HUMAN_OVERRIDE blocks WITHOUT consuming a retry slot?
  Where the plan offers "either X or Y" (should be nowhere in REV 3), lift to §6 Q. Any place
  a builder could reasonably route the write through `confirms()` incorrectly (e.g. asking the
  oracle about a stale observation from before the write) is a finding.

**Plan-review findings are fixed IN THE PLAN before any build dispatch.**

**Orchestrator hand-check before deploy (Tier 3 mandate):**
1. `git grep` re-run: every `climate.set_temperature` / `climate.set_preset_mode` /
   `climate.set_hvac_mode` service call outside the funnels MUST be zero.
2. Re-run the 10-site inventory against `Strategy.return_borrow`; every site maps.
3. Real source mutation of `Strategy.return_borrow` — the full suite MUST go RED with a specific
   named failure per site.
4. Grep for `.attributes["preset_mode"]` / `.attributes.get("preset_mode")` — every match is
   either inside `Strategy.observe()` or annotated `# preset_mode: display-only`.
5. D0 replay in test — zero strand-equivalents on the fixture.
6. **REV 3:** Real source mutation of each of the 5 oracle DATA rows — full suite MUST go RED
   with a specific named failure per row.
7. **REV 3:** Grep for direct `hold_activity` reads outside `CarrierStrategy.observe()` /
   `.confirms()` — zero (the "trust hold_activity" corollary is DELETED; only the oracle sees it).

**Operator checkpoint BEFORE deploy:** surface D-review outcome, the invariant proof (grep +
mutation + replay), the enumerated 10-site coverage, the D0 findings, the oracle DATA table with
citations to D0, and any `[CONFIRMATION EXHAUSTED]` cases observed in replay. Explicit go required.

---

## 9. Sequencing / dependencies

1. Stage A ships (`HVAC-SETHVACMODE-CHOKEPOINT-1` + `climate_write` durable log). **SHIPPED
   v5.103.16 2026-09-26.** One clean day of rows is a hard input — timer running.
2. This doc gets its two plan reviews (oracle-completeness + adversarial-build-prediction,
   REV 3-retargeted per §8). Findings folded in place.
3. **D0 probe runs** (§3; Parts A + B + C, including the operator controlled test). Discrimination
   verdict folded into D2 fixture table AND D2.7 oracle DATA AND — if the verdict shifts the
   mechanism — into the invariant.
4. Build in isolated worktree `.claude/worktrees/hvac-w1b-thermostat-definition` on
   `feature/hvac-w1b-thermostat-definition` off latest `develop`.
5. Build order: **D0 output → D1 → D4 → D5 → D2 (full; includes D2.7 oracle DATA + the D6
   migration) → D3.**
6. Four framing-disjoint reviews on the D1-D5 build in parallel. Fix CRITICAL/HIGH; re-run
   D's enumeration; orchestrator hand-check (§8).
7. Operator checkpoint. On go: deploy.
8. Live-validation write-back into `README_v<version>.md` per state-of-play discipline.
9. Post-deploy disposition query at N≥10 non-nudge return episodes per zone (§7) — including
   the REV 3 `climate_write` re-issue-rate row and the human-override-not-overwritten row.

**No soak.** The ship gate is a disposition query, not a calendar watch.

---

## Operator decisions — 2026-09-26 ("Accept recs") — BINDING
1. `set_activity_setpoint` NOT adopted this cycle — nudges stay on `set_temperature`.
2. No in-code schedule-boundary guard — the operator reduces the zone 2/3 Bryant schedules (working assumption: only URA controls).
3. Reclaim DELAY for a URA-owned manual hold with no live borrow = 1 tick (same-tick eligible), plus a separate kill switch.
4. Ship-gate disposition: N ≥ 10 exercised return episodes per zone, 10-min falsifier window; pre-deploy gate = replay.
5. No Nest stub.
6. `POST_WRITE_INTERCEPT_S` / `PRESET_TTL_S` (and sibling timing values) are Rung 1 module constants.
7. On Temp-Arrester-Override / immune-person expiry, URA reclaims the HUMAN hold to S1's current target preset (not a snapshot); Comfort Grace is not part of D3.
