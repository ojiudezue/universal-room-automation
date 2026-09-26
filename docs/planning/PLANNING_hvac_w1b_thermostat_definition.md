# PLANNING — HVAC W1-B: Per-brand thermostat definition (Carrier/Bryant first) — REV 2

**Card:** `HVAC-W1-THERMOSTAT-DEFINITION` (Stage B).
**Tier:** **Tier 3** (delicate; threads a shared primitive across ~10 return sequences; single-missed-site is the exact failure class the parked `HVAC-EXCURSION-RESTORE-UNIFIED-1` cycle exhibited).
**Depends on:** W1-A (`HVAC-SETHVACMODE-CHOKEPOINT-1` + one durable write log). Stage A ships first; one clean day of `climate_write` rows is a hard input to this cycle's D0 probe.
**Operator posture:** nudges stay ON; AC ramp ON; per-brand behaviour discovered in detail behind a simple generic interface; Tier-3 double-checkpoint (before build AND before deploy).
**Reference reads (mandatory):**
`docs/Coordinator/HVAC_ARCHITECTURE_STATE_OF_PLAY.md` (all sections — the §10 corrections ledger through C20 especially),
`docs/Coordinator/THERMOSTAT_DEFINITION_CARRIER_BRYANT.md` rev 2 (companion, ships D0 of this cycle).

## Rev-2 change log — how the two Tier-3 plan reviews folded

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

> **INV-W1B:** For every URA-initiated borrow that returns cleanly on a Carrier/Bryant zone, no
> Carrier-side manual hold appears at URA's own written values within the falsifier window (10 min
> after the return sequence completes). AND: URA never emits a preset lockout ledger row against
> an observed hold that URA's ProvenanceStore records as URA-owned. AND: while a borrow is live
> for an entity, S1 and the arrester write nothing to that entity.

Falsification shape: over the ship-gate exercised-episode floor (N≥10 non-nudge return sequences
plus every nudge return in a clean 72 h window on all three zones), zero episodes where a
manual-hold appears within 10 min of the return AND URA's ProvenanceStore identifies the observed
hold as URA-owned AND URA books a lockout instead of reclaiming.

**INV carve-outs (explicit non-invariants):**
- A genuine `set_temperature` write by a human (dial or app) at values URA did not write is NOT
  URA-owned — those still lock URA out. This is correct behaviour.
- The vendor-schedule race between `resume` and `pin` may still cause a brief unwanted state; see
  §6 Q2. Not this cycle's invariant.
- `HVAC-COMPOSE-AWAY-THROTTLE-STORM-BLOCKER-1` and `HVAC-RESTORE-WRITERS-STRAND-EMPTY-NIGHT-ZONE-1`
  are unblocked by moving `_last_emitted_range` ownership into the funnel (see §5.D2a) but the
  D9 dormant-switch enablement is not this cycle.
- No Nest strategy is landed. Interface accepts one; code lands only when hardware is available.
- `hvac_activity_log` writer-attribution across integrations is not solved (integration surface
  does not expose it).

---

## 1. Institutional context verified

### 1.1 Prior-art scan (Tier 2+ mandate; every proposed piece cited REUSE-or-BUILD)

| Proposed piece | Verdict | Existing at |
|---|---|---|
| Preset-write "resume-then-pin" mechanism | REUSE | `hvac_setpoint.py:288-410`; `_needs_resume_first` `:181-226` |
| `climate.set_temperature` funnel | REUSE | `hvac_setpoint.py:229-286` |
| `climate.set_hvac_mode` funnel | REUSE (from W1-A) | Stage A build |
| Durable per-write log | REUSE (from W1-A) | Stage A build (`climate_write` table with verb, zone, site, values, reason, wrote_at) |
| Excursion primitive `begin_excursion` / `return_excursion` (bookkeeping only) | REUSE — extend, don't replace | `hvac_excursion.py:766` / `:871-1040`; docstring `:886-888` |
| Excursion snapshot fields (`pre_preset`, `pre_target_low/high`, `pre_hvac_mode`, kind) | REUSE + extend read | `hvac_excursion.py` snapshot code + persisted `hvac_excursion_state` row |
| Per-entity runtime state (`_last_emitted_range` `hvac.py:521`; `_suppressed_until` `hvac_override.py:235`; `_nudge_pre_preset` `:262`; `_override_active` `:205`; excursion `_rows` `hvac_excursion.py:201`) | REUSE in place; ownership migrates for `_last_emitted_range` (see §5.D2a) | as cited |
| Suppression provenance tag `_suppress_kind` (`hvac_override.py:243-262`; nudge-only today) | REUSE + extend to all borrow kinds | as cited |
| BORROW_ACTIVE derivation (live excursion row + in-flight nudge) | BUILD from existing state | `hvac_excursion.py` rows + `hvac_override.py:_nudge_pre_preset` |
| Provenance-aware `observe()` and `classify()` | BUILD; no such helper today | uses W1-A `climate_write` + `hvac_excursion_state` rows |
| Presets-only borrow-return migration (10 return sequences, F7) | BUILD in same edit per site | see §5.D2 verified inventory |
| Per-brand strategy dispatch (memoized per BRAND via registry platform) | BUILD; minimal | HA entity registry |
| Zone-keyed S10/DPM baseline accessor as its OWN concept | BUILD as separate helper | today: `hvac_predict.py:889/943/1526`, `hvac.py:429/521/3023/3068` |
| Coherence classifier `URA_ECHO_MANUAL` / `STALE_MANUAL-by-profile-match` | **DELETE from spec (C20)** | premise refuted; do not build |

### 1.2 Prior planning docs consulted (headers or bodies)

- `docs/planning/PLANNING_hvac_governed_excursion.md` — rev-6 banner (lease gate stripped; do not
  rebuild) + kinds enum + `return_excursion` bookkeeping-only invariant. BODY skimmed.
- `docs/planning/PLANNING_hvac_excursion_restore_unified.md` — the parked D2/D3/D4 rework (3
  CRITICALs from 2026-08-26 four-review). W1-B RESPECTS the parking: does not rebuild the D2 AST
  governance gate, does not rebuild the D3 manual-preset recovery interlock, does not re-introduce
  the S14 off-phase-ceiling token. Presets-only returns + provenance ownership are disjoint —
  removes the MANUAL by construction rather than by post-hoc governance.
- `docs/planning/PLANNING_hvac_live_room_establishment.md` — Stage-0 in-flight; consumers of
  `conditioning_retreat_ok` overlap with S1 preset writes. W1-B does not change that gate.
- `docs/planning/PLANNING_hvac_zone_conditioning_demand.md`,
  `..._d5_reframe_occupancy_gate.md`, `..._demand_knobs_and_observability.md` — HEADERS only;
  downstream consumers of preset flips, not producers.
- `docs/planning/AUDIT_thermostat_write_paths_2026_09_16` — inventory result folded into parent
  card body: `set_preset_mode` 10/10 funnelled, `set_temperature` 11/11 funnelled, `set_hvac_mode`
  7/7 bypassing (Stage A scope).

### 1.3 Memory bodies pulled

- `feedback_extend_existing_never_rebuild.md`, `feedback_wire_in_anchor_mandatory.md`,
  `feedback_suppression_needs_discharge.md`, `feedback_mutation_verification_pycache_staleness.md`,
  `feedback_no_soak.md`, `feedback_do_robust_fix_not_bandaid_and_card.md`,
  `feedback_tier2plus_prior_art_scan.md`, `feedback_falsify_before_asserting.md`,
  `feedback_hollow_test_anchors.md`, `feedback_coincidental_equality_masks_concept_split.md`
  (this last one now explicitly WHY the coherence classifier failed — the `preset_mode==manual /
  hold_activity==named-preset` coincidence was a happy-path artifact, not the discriminator we
  hoped).

### 1.4 Design docs read

- `docs/Coordinator/HVAC_ARCHITECTURE_STATE_OF_PLAY.md` — full read; C16-C20 folded.
- `docs/Coordinator/THERMOSTAT_DEFINITION_CARRIER_BRYANT.md` rev 2 — ships D0 of this cycle.
- `docs/Coordinator/HVAC_COORDINATOR_MANUAL.md` — SKIMMED; superseded by state-of-play in the
  areas this cycle touches.

### 1.5 Code locations surveyed end-to-end

- `custom_components/universal_room_automation/domain_coordinators/hvac_setpoint.py` (funnels).
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
  carrier_data_update_coordinator.py` (behaviour cited in companion doc).

---

## 2. Non-goals (explicit)

- No coherence classifier (`URA_ECHO_MANUAL` withdrawn).
- No profile-setpoint match classifier (ha_carrier does not expose named-profile setpoints).
- No Nest strategy code.
- No `set_activity_setpoint` adoption for nudges this cycle (see §6 Q1).
- No schedule-boundary guard against the vendor resume race (see §6 Q2).
- No live-guard-wipe defense in URA (integration behaviour; not URA's to solve — but D0 probe
  measures it so we know the cost we accept).
- No enablement of D9 / F2 / F4 (Custom Preset Ranges); this cycle only unblocks by moving
  `_last_emitted_range` ownership.

---

## 3. D0 — Read-only measurement probe (MANDATORY, blocks design freeze)

Per Measure-Before-Build: the leading strand mechanism (companion doc §9 item 1) is UNVERIFIED.
D0 is a one-shot script that reads existing data — no runtime code, no live experiment.

**Data sources** (all already exist):
- URA DB: `ac_ramp_events` (nudge start / restore / settled rows), `hvac_excursion_events`,
  `ura_activity_log` (preset_change, preset_change_locked_out, override_detected, comfort rows).
- W1-A `climate_write` durable log (from Stage A ship — one clean day of rows is a prerequisite).
- HA recorder `home-assistant_v2.db` on the live system: `climate.thermostat_bryant_wifi_studyb_zone_1`,
  `climate.up_hallway_zone_2`, `climate.back_hallway_zone_3` state + attribute history for
  `preset_mode`, `hold_activity`, `temperature`, `target_temp_high`, `target_temp_low`,
  `hvac_mode`, `next_activity_time`.

**Per-episode extraction** (for every nudge return AND every non-nudge borrow return in the window):
1. Identify the return sequence in `climate_write`: what verbs fired, in what order, at what
   times, with what values.
2. For the S7 preset call in each nudge return: did the funnel emit a `resume` first (grep the
   log for the resume kwarg), or a bare pin?
3. At the timestamp of each `set_preset_mode` call, what was `hold_activity` — was it already
   `manual` (so `_needs_resume_first` should have fired) or something else?
4. When did the observed `manual` appear afterwards, on BOTH `preset_mode` AND `hold_activity`
   feeds (recorder attribute history)? Compute onset lag for each feed.
5. Between the return sequence and the onset, was there any refresh-triggering event visible
   (attribute jump on other zones on the same account = full reconcile signature)?
6. Was another zone / system on the same account written between return and onset — any
   resume/full-refresh trigger from a sibling (C16 wipe candidate)?

**Output shape (per episode + roll-up):**
- Table row: `(zone, return_ts, verbs_in_return, s7_used_resume_first, hold_activity_at_pin,
  onset_lag_status_s, onset_lag_config_s, sibling_write_between, refresh_signature)`.
- Roll-up: distribution of onset lag on both feeds; frequency of (a) bare pin over anonymous
  hold, (b) resume-then-pin over anonymous hold, (c) sibling write in the interval, (d) full
  refresh in the interval.
- **Config-combination matrix** built passively from the extraction: for each observed
  combination of (verb order, hold state at pin, sibling activity, refresh coincidence),
  count strand vs no-strand.

**Discrimination**:
- If (a) dominates strand cases -> the funnel's resume-decision race is the mechanism; the fix is
  presets-only returns + snapshot correctness (§5.D2).
- If (b) dominates -> the shared-guard wipe (C16) is the mechanism; the fix is what we can do
  from our side is a no-op reclaim rather than defending the pin (URA has no lever inside the
  integration).
- If both are represented -> both fixes needed (still all inside §5.D2 scope).
- If neither -> return to the operator; the mechanism is something we have not enumerated.

**Non-negotiable:** the plan does not proceed to build until D0 has run and its output is folded
into the D2 fixture table.

---

## 4. Deliverable order (rev 2)

1. **D0** — one-shot read-only probe (this section §3).
2. **D1** — generic strategy interface (behaviour-neutral).
3. **D4** — reclaim delay knob + kill switch, module consts.
4. **D5** — fully specified generic default (setpoint-drift human detection; no-preset case;
   return order).
5. **D2** — Carrier strategy: BORROW_ACTIVE gate, presets-only returns per-site migration,
   provenance ownership, no-op suppression, `_last_emitted_range` ownership move, snapshot
   correctness, S10/DPM zone-keyed baseline accessor as its own concept.
6. **D3** — knob-expiry reclaim wiring (TAO / immune-person expiry — Comfort Grace removed,
   see §6 Q7).
7. **Live-validation write-back** into README (state-of-play discipline).
8. **D6 IS FOLDED INTO D2 (per plan review #16).** No separate cleanup pass — each per-site edit
   replaces the site's inline `(setpoints -> preset)` pair with the strategy call in the same
   edit, so the migration cannot half-land.

---

## 5. Deliverables

### D0 — Read-only measurement probe

Spec above (§3). Output artifact: `docs/planning/AUDIT_hvac_w1b_strand_mechanism_2026_09_XX.md`
containing the extraction table, roll-up, and discrimination verdict. That artifact IS the input
to the D2 fixture table.

**Acceptance:**
- **Verify:** the D2 fixture table cites every strand episode in the D0 output as a named test.
- **Verify:** the discrimination verdict is present and folded into the §0 invariant if needed
  (e.g. if C16 wipe dominates, the invariant may relax the "no manual within 10 min" clause and
  strengthen the "URA never books lockout on URA-owned" clause).

### D1 — Generic strategy interface (behaviour-neutral)

A stateless module `domain_coordinators/hvac_strategy.py` exposing (finding #13):

```
strategy_for(hass, entity_id) -> Strategy    # cached per BRAND (by registry.platform); never cache fallback
Strategy.observe(hass, entity_id) -> HoldObservation
Strategy.hold_preset(hass, entity_id, preset, *, gate=None, blocking=False, zone_id, reason, site)
Strategy.borrow(hass, entity_id, kind, *, gate, duration, freeze, snapshot, zone_id, reason, site)
Strategy.return_borrow(hass, entity_id, snapshot, *, gate=None, zone_id, reason, site)
```

`borrow(...)` accepts EVERY parameter `begin_excursion` accepts today plus `gate`, `duration`,
`freeze` (finding #13; `borrow` is a superset). `hold_preset` inherits the funnel's gate contract.
Every strategy method returns a `WriteResult` (success bool + failed-verb detail) so callers can
implement failed-return retry (finding #10).

`HoldObservation` = `{preset_mode, hold_activity, target_high, target_low, hvac_mode, read_at,
observed_at_source: 'live_state'}`. **No Carrier vocabulary in the interface** (finding #13
constraint) — words like `resume`, `manual`, `hold_activity` only appear inside `CarrierStrategy`.

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
indirection.

**Acceptance:**
- **Test:** `test_strategy_dispatch_by_registry_platform` — Carrier entity -> CarrierStrategy;
  fake platform -> generic default. Discriminating: the fake platform's `hold_preset` MUST NOT
  emit a `resume` even when observation says `hold_activity == "manual"`.
- **Test:** `test_strategy_cache_by_brand` — two distinct Carrier entities return the same
  `CarrierStrategy` instance; a fake-platform entity returns a different instance; a registry
  miss on a Carrier entity returns the generic default without polluting the cache
  (subsequent lookups after the registry recovers must return the CarrierStrategy).
- **Live:** post-restart, a grep confirms all callers import through `hvac_strategy`; every
  existing behaviour byte-identical (name-diff on the suite).

### D2 — Carrier strategy: presets-only returns, BORROW_ACTIVE gate, provenance, snapshot correctness

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

#### D2.3 Provenance ownership (finding #3, F5, F16 — replaces coherence classifier)

New in-memory helper `ProvenanceStore` (module-level, keyed per entity):

```
ProvenanceStore.record(entity_id, verb, values, wrote_at, snapshot_preset)
ProvenanceStore.classify(entity_id, observation) -> HoldClassification
ProvenanceStore.clear(entity_id, verb)     # every actual write clears every verb's record for entity
ProvenanceStore.rebuild_on_boot(hass)      # from hvac_excursion_state + W1-A climate_write last row
```

`HoldClassification` ∈ `{NAMED_HOLD, URA_OWNED_MANUAL, HUMAN_MANUAL, NO_HOLD}` (no
`URA_ECHO_MANUAL`, no `STALE_MANUAL_BY_PROFILE_MATCH`).

**Classification:**
- `observation.preset_mode != "manual"` -> `NAMED_HOLD` or `NO_HOLD`.
- `observation.preset_mode == "manual"`:
  - if URA has an in-window `set_temperature` record for this entity whose values match
    `observation.target_low/high` AND no URA `set_preset_mode(named)` has fired since -> `URA_OWNED_MANUAL`.
  - else -> `HUMAN_MANUAL`. **NOTE:** a config-manual observation AFTER a URA NAMED write is
    always HUMAN (F9): the named write set config to the named preset; a subsequent manual must
    have been placed by something else.

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
| `NAMED_PROFILE_MATCH_TOLERANCE_F` (rev-1) | **DELETE** | — | Killed by C20 / F5 (profile setpoints not queryable) |

**Restart rebuild (finding #9):** on integration setup, `ProvenanceStore.rebuild_on_boot`:
1. Loads still-open `hvac_excursion_state` rows -> re-populates in-flight nudge / borrow state.
2. Loads the LAST `climate_write` row per entity (verb, values, wrote_at) from W1-A durable log.
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

#### D2.5 No-op write suppression at the funnel (finding #5)

- Suppress iff (a) intended `(verb, values)` equal the funnel's last-sent record for this entity
  AND (b) the observed state equals those values.
- Any actual write to the entity clears EVERY verb's last-write record for that entity.
- Observed divergence from the last-write record clears that record.
- Re-asserts and reclaims are exempt (they must fire even when values match).

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

**Acceptance for D2 (integrated):**
- **Verify:** service-call-count tests pass for all 10 return sequences (§D2.4).
- **Verify:** BORROW_ACTIVE per-kind falsifier tests pass (§D2.1).
- **Verify:** ProvenanceStore restart-safe test passes (§D2.3).
- **Verify:** `_corrective_writes_suppressed` + active comfort grant gate the reclaim path (F6);
  discriminating tests.
- **Sensor:** `ura_activity_log` row `preset_change_locked_out` count drops materially per zone.
- **Test:** `test_carrier_return_presets_only[all 10 sites]` (mutation-anchored).
- **Test:** `test_provenance_classify_matrix` — matrix built from D0's config-combination table.
- **Test:** `test_no_op_write_suppression_at_funnel` — repeat write with identical values +
  matching observation emits zero service calls; observed divergence clears the record and next
  write fires.
- **Test:** `test_zone_baseline_split_semantics` — S10/DPM baseline reads and writes match the
  pre-migration behaviour byte-for-byte.
- **Test:** `test_hold_activity_after_named_write_is_always_human` (F9 corollary).
- **Test:** `test_borrow_active_gates_s1_and_arrester` (mutation-anchored per BORROW_ACTIVE
  source).
- **Live:** post-restart, D0's config-combination matrix REPLAYS as a fixture against the
  strategy in the test suite AND the ship gate query on the running instance shows zero
  falsifying episodes over the 72 h window (see §7).

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

### D3 — Knob-expiry reclaim wiring (finding #8, F6, Q7 pending)

Per operator challenge 2026-09-25 ("we have a knob that says don't override till next change, and
that knob times out"): TAO and immune-person hold expire against a hold that today does not get
released.

D3 wires each expiring knob to a strategy-level release:
- On expiry, if `Strategy.classify()` returns `URA_OWNED_MANUAL` -> `hold_preset(snapshot.pre_preset)`.
- On expiry, if `Strategy.classify()` returns `HUMAN_MANUAL` -> **Q7 PENDING** (operator: reclaim
  to S1's current target, i.e. today's house-state preset, rather than the snapshot? Or leave
  the human hold alone?). D3 ships whichever branch the operator picks.
- BORROW_ACTIVE gates every reclaim.
- `_corrective_writes_suppressed` and active comfort grant gate every reclaim (F6).
- **Comfort Grace REMOVED from D3** (finding #8): its grant expiry is not the right release
  channel (it wrote nothing today, and adding a write there conflates comfort with reclaim).

**Acceptance:**
- **Test:** `test_tao_expiry_reclaims_ura_owned_manual` — TAO expires with a URA-owned manual
  present; exactly one `hold_preset(snapshot.pre_preset)` fires; BORROW_ACTIVE-gate discriminating
  test (no fire while a borrow is live).
- **Test:** `test_immune_person_expiry_reclaims_ura_owned_manual` — same shape, different knob.
- **Test:** `test_comfort_grace_does_not_reclaim` — Comfort Grace expiry emits nothing (removed).
- **Test:** whichever Q7 branch ships gets its own discriminating test.
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

**Acceptance:**
- **Test:** `test_generic_default_no_resume_emitted` — stub non-Carrier entity gets a direct pin
  even when `hold_activity == "manual"`.
- **Test:** `test_generic_default_setpoint_drift_is_human` — observation setpoints change with no
  ProvenanceStore record; classify returns `HUMAN_MANUAL`.
- **Test:** `test_generic_default_no_presets_fallback` — entity without `preset_modes` gets
  setpoints-only return path.
- **Non-goal:** no Nest strategy code. Interface accepts one.

---

## 6. Operator questions

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
6. **`POST_WRITE_INTERCEPT_S` and `PRESET_TTL_S` rung placement.** Proposed Rung 1 (module const,
   review-only). Operator agree, or Rung 3?
7. **On TAO / immune-person expiry against a HUMAN hold: reclaim to S1's current target (today's
   house-state preset), or leave the human hold alone?** Finding #8. This is a comfort-vs-respect
   trade — reclaiming means the human's dial-set temperature is overwritten when their protection
   expires, at whatever URA thinks is currently right; leaving means the hold stays until the next
   forced-away write. Recommendation: **reclaim to S1's current target** — that is what "expiring
   the immunity" means in plain English; the immunity was the reason to leave it alone, and its
   expiry is the operator's own signal that the immunity is done. But this is genuinely an
   operator call.

---

## 7. Ship gate — disposition query, not soak (finding #11)

**Pre-deploy gate — replay:** after D0 output is folded into the D2 fixture table, run the D2
matrix against the strategy code in test. If the replay produces any strand-equivalent
(URA-owned manual + lockout ledger row) in the fixture, deploy is BLOCKED.

**Post-deploy gate — disposition query at day 3 (or first N≥10):**
- Exercised-episode floor: at least **N=10 non-nudge return episodes per zone** in the post-deploy
  window (nudges will exceed this; non-nudge borrows are the rarer, more expensive case).
- Falsifier threshold: **10 min** — any strand-equivalent episode within 10 min of a URA return
  fails the gate.
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
  presets-only return per site; per-site edit correctness.
- **Reviewer B — integration / state-machine integrity.** Window discharge (every start has an
  end); BORROW_ACTIVE gate coverage (S1 + arrester + reclaim); restart rebuild correctness; no
  regression on `HUMAN_MANUAL` lockout; no interaction with parked D2/D3/D4 governance;
  shared-account guard wipe consequences documented; failed-return retry with discharge and
  gate pass-through.
- **Reviewer C — test authority via REAL per-site source mutation.** Each of the 10 return sites
  gets its own mutation; global monkeypatch is NOT sufficient. Bytecode disabled + `__pycache__`
  cleared each drill. Independent re-derivation of the site list — this doc's inventory is a
  hypothesis, not a spec.
- **Reviewer D — adversarial completeness / diff-blind.** Restate INV-W1B in reviewer's own
  words; re-enumerate the ENTIRE thermostat-write surface across `hvac*.py` — INCLUDING
  pre-existing code, not just the diff — for any missed borrow-return site, any writer that
  bypasses the strategy, any classifier consumer that reads `preset_mode` raw without going
  through `observe()`. D also enumerates the shared-account guard wipe triggers and confirms the
  invariant's carve-outs are complete.

**Two plan reviews (this document, before build dispatch):** completeness (re-enumerate every
surface — including this doc's 10-site inventory) and build-prediction (predict what a builder
gets wrong; ambiguity is a finding).

**Orchestrator hand-check before deploy (Tier 3 mandate):**
1. `git grep` re-run: every `climate.set_temperature` / `climate.set_preset_mode` /
   `climate.set_hvac_mode` service call outside the funnels MUST be zero.
2. Re-run the 10-site inventory against `Strategy.return_borrow`; every site maps.
3. Real source mutation of `Strategy.return_borrow` — the full suite MUST go RED with a specific
   named failure per site.
4. Grep for `.attributes["preset_mode"]` / `.attributes.get("preset_mode")` — every match is
   either inside `Strategy.observe()` or annotated `# preset_mode: display-only`.
5. D0 replay in test — zero strand-equivalents on the fixture.

**Operator checkpoint BEFORE deploy:** surface D-review outcome, the invariant proof (grep +
mutation + replay), the enumerated 10-site coverage, and the D0 findings. Explicit go required.

---

## 9. Sequencing / dependencies

1. Stage A ships (`HVAC-SETHVACMODE-CHOKEPOINT-1` + `climate_write` durable log). One clean day of
   rows is a hard input.
2. This doc gets its two plan reviews (completeness + build-prediction). Findings folded in place.
3. **D0 probe runs** (§3). Discrimination verdict folded into D2 fixture table AND — if the
   verdict shifts the mechanism — into the invariant.
4. Build in isolated worktree `.claude/worktrees/hvac-w1b-thermostat-definition` on
   `feature/hvac-w1b-thermostat-definition` off latest `develop`.
5. Build order: **D0 output → D1 → D4 → D5 → D2 (full; includes the D6 migration) → D3.**
6. Four framing-disjoint reviews on the D1-D5 build in parallel. Fix CRITICAL/HIGH; re-run
   D's enumeration; orchestrator hand-check (§8).
7. Operator checkpoint. On go: deploy.
8. Live-validation write-back into `README_v<version>.md` per state-of-play discipline.
9. Post-deploy disposition query at N≥10 non-nudge return episodes per zone (§7).

**No soak.** The ship gate is a disposition query, not a calendar watch.
