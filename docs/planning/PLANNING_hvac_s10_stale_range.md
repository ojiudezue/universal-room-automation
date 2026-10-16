# PLANNING — HVAC S10 stale-range re-write after a preset change

**Card:** `HVAC-S10-STALE-RANGE-AFTER-PRESET-CHANGE-1`
**Thread:** hvac
**Status:** pre_planning
**Rev:** **3** (2026-10-15) — fully revises Rev 2 against the Rev 2 re-review
appended to `docs/reviews/code-review/plan_hvac_s10_review.md` (R1-R7 FIX-REQUIRED).
Rev 2's observer-on-the-coordinator wiring is withdrawn (R1): the stamp lives on
`ZoneState` and `_s10_zone_skip_reason` reads it off the zone, removing the back-
reference the plan did not specify. Rev 2's D2 as written (reset on APPLIED via
`_s10_success`) is unreachable (R2): APPLIED never calls `_s10_success`; D2 is
re-stated as "reset on CONFIRMED success" (option (i), SKIPPED_ALREADY_CORRECT or
a matching view at the limit) and INV-S10-LATCH-RESET + T9 track that.
**Tier:** **Tier 2-DB (operator-elevated)** — see §"Tier + framings".
**Date:** 2026-10-15
**Branch (intended):** `plan/hvac-s10` on worktree `.claude/worktrees/hvac-s10-plan`.

---

## Measurement first (read-only recorder probe, 2026-10-15)

A one-shot probe over the live recorder + the live store answered the "measure before
build" gate; the result reshapes the plan. (Standing rule
`feedback_measure_before_build.md`.)

- **Scope.** `ura_activity_log` since 2026-10-13 (CPR live on zone_3), joined to
  `climate_write` rows with `json_extract(details_json,'$.site') IN
  ('S10_preset_range','S10_preset_range_restore')` AND `json_extract(details_json,
  '$.zone_id')='zone_3'`. (**F8**: `zone_id` lives in JSON `details_json`, not as a column —
  Rev 1's SQL was wrong.)
- **Volume.** **3** S10 writes against zone_3 since CPR went live. **1** was a FAILED
  wire call; the other 2 APPLIED cleanly.
- **The one failure (the subject of this plan).** 2026-10-14 05:48:52Z, zone_3,
  `site=S10_preset_range`, `preset=away`, `wire_ok=false`,
  `error=HomeAssistantError`, elapsed **~0.3 ms** (a LOCAL raise, no cloud call).
  Preceded 299 s earlier (05:43:52Z) by an S1 `preset_change` to `away` with
  `reason=vacant_past_grace`. The HA entity's setpoint legs did not update to the new
  away range (66/80) until **05:50:54Z** — **422 s** after the S1 write and **~122 s
  after the S10 attempt**. During that window `preset_mode` and `hold_activity`
  already said `away`.
- **Base rate.** Across all zone_3 preset segments since 2026-10-01 (n=544), only
  **1** exhibited a prior-range stale read; ~500 flipped instantly. Zones 1 + 2 are
  not yet in `hvac_s10_rollout_zone_ids` and have no S10 writes.
- **Latch store.** `.storage/universal_room_automation.hvac_zone_state` on
  2026-10-15: `zone_3 away|apply failures: 1, writes: 2, latched: false`,
  `last_write_iso` on an APPLIED write — the counter does NOT clear on success
  (**F4**). Snapshots for `away` are the correct 66/80 defaults (not poisoned).

**What the probe refutes** (unchanged from Rev 2 — see Rev 2 for the ha_carrier
chain + the Rev 1 cooldown refutation).

**What the probe does NOT establish.** Mechanism is **PARTIAL / UNVERIFIED (n=1)**.
A single HomeAssistantError consistent with "unresolvable activity" but also with
any other local raise under `async_set_activity_setpoint`. The acceptance tests
below discriminate "stale legs, landed write" from "unresolvable activity, rejected
write" (per F6 / `feedback_falsify_before_asserting.md`).

---

## Review resolution table

Rev 1 findings F1-F8 were resolved in Rev 2 (see Rev 2's resolution table + the
re-review verdict `F1 F2 F3 F7 F8 RESOLVED; F4 F5 F6 PARTIAL`). Rev 3 addresses the
Rev 2 re-review R1-R7. Every row below cites the exact code line verified against
`develop @ 05314a3c4` before writing — not inherited from Rev 2.

| # | Finding (short) | How Rev 3 resolves it |
|---|---|---|
| R1 | Observer site cannot do what Rev 2 said: `hvac_zones.update_zone_climate_state` at `hvac_zones.py:651-670` sets `preset_mode` via `preset_of_for` (:666) and reads NOTHING about `hold_activity` (verified: `grep hold_activity hvac_zones.py` = 0 hits). `ZoneManager.__init__` at `:279` holds no coordinator reference, so the Rev 2 `coordinator._note_observed_preset_change(...)` call needs unspecified back-wiring. | **Stamp lives on `ZoneState`, not on the coordinator.** Add three fields to the `ZoneState` dataclass at `hvac_zones.py:127-143` (right after `preset_mode: str = ""` at :137 / the current/target block ending :143): `prev_preset_mode: str = ""`, `prev_hold_activity: str = ""`, `last_observed_preset_change: datetime | None = None`. In `update_zone_climate_state` (`hvac_zones.py:651-670`), after the existing `zone.preset_mode = preset_of_for(...)` at :666, read `hold_activity` as the **raw climate attribute**: `new_hold = state.attributes.get("hold_activity", "") or ""`. Both reads are the inputs to the stamp decision (see R3 for sentinel handling). The stamp fires when EITHER the readable `preset_mode` or the readable `hold_activity` differs from its stored prev. `_s10_zone_skip_reason` reads `zone.last_observed_preset_change` directly — no coordinator back-reference, no map on the coordinator. Both signals are read because the Carrier post-write transition can land `preset_mode` first and `hold_activity` later (or vice versa); either edge opens the staleness window and both must arm it. The W1-C P2 `preset_of_for` indirection for `preset_mode` is PRESERVED (brand-adapter projection); `hold_activity` is read as the raw Carrier attribute (Generic/ecobee return `""` for it, which is sentinel-skipped, so this does not alter their path). |
| R2 | D2 as written in Rev 2 is unreachable: `_s10_write_one` step 12 at `hvac.py:4686-4704` increments `writes` on APPLIED and never calls `_s10_success`; `_s10_success` runs ONLY on `SKIPPED_ALREADY_CORRECT` at `:4707` and on a matching view at the limit (near :4596). So the Rev 2 text "APPLIED ... ALSO resets failures" is false; the 2026-10-14 record (`failures=1, writes=2`) would keep `failures=1` until a later SKIPPED_ALREADY_CORRECT. | **Option (i): reset failures only on CONFIRMED success.** The APPLIED path is a wire return, not a confirmation (operator ruling A4 2026-10-05, cited in the `_s10_success` docstring at `hvac.py:4770-4778`). D2's single new line goes in `_s10_success` at `hvac.py:4779` (`rec["writes"] = 0`): add `rec["failures"] = 0` on the next line. That reset runs on BOTH confirmation paths — the SKIPPED_ALREADY_CORRECT branch at :4707 AND the limit-matching view call near :4596 — and nowhere else. **INV-S10-LATCH-RESET restated** (see Falsifiable invariant §) to name `WriteStatus.SKIPPED_ALREADY_CORRECT` + the limit-matching-view path as the only reset triggers. **T9 fixed** (see Acceptance): the record setup has `failures=2, writes=0`, the adapter returns `SKIPPED_ALREADY_CORRECT`, and the assertion is `failures=0, writes=0` after `_s10_success`. Alternating-raise/APPLIED defeat case (Rev 2 re-review §"D2 reachable defeat case") is accepted: `call_failed` is defeated but `writes` still reaches 3 and the limit-view path at :4590 latches `not_sticking` if the writes don't stick — operator ruling A4 is preserved. |
| R3 | Boot/first-read is unspecified. `ZoneState.preset_mode` defaults to `""` at `hvac_zones.py:137` (verified); the boot refresh at `hvac.py:1555` moves it from `""` to the live value. A literal "differs from previous RAM copy" rule stamps every zone at every boot and holds S10 for 600 s (2-3 ticks) after each restart. The `unavailable` early return at `hvac_zones.py:658` keeps the copy, but `unknown` is NOT handled there — it falls through to `preset_of_for(..., "")` and becomes `""`, producing TWO stamps across one unknown flap. | **Rule (explicit).** Treat `""` and `"unknown"` as **unreadable** on BOTH `preset_mode` and `hold_activity`. In `update_zone_climate_state` immediately after the attribute reads: compute `new_preset = zone.preset_mode` and `new_hold = state.attributes.get("hold_activity", "") or ""`. If either `new_preset` is in `{"", "unknown"}` OR `new_hold` is in `{"", "unknown"}` → treat the whole observation as unreadable: DO NOT update `prev_preset_mode` / `prev_hold_activity`, DO NOT stamp. Then: if `prev_preset_mode == ""` AND `prev_hold_activity == ""` (first-ever readable observation after boot or reload) → **seed** the prev fields with the readable `(new_preset, new_hold)` WITHOUT stamping (`last_observed_preset_change` stays None). On every subsequent readable observation, stamp iff `new_preset != prev_preset_mode OR new_hold != prev_hold_activity`, then update both prev fields. Net: boot does not hold S10; a single unknown flap does not stamp; a real preset transition stamps exactly once. Chosen over "stamp on boot and accept 600 s delay" because the boot-refresh is a UI/attribute read, not a Carrier post-write transition — the staleness window is scoped to real writer-induced transitions. If a boot read ever lands inside a real Carrier transition, the first NEXT readable observation whose preset/hold differs from the seed will stamp correctly. |
| R4 | On a flapping feed (zone_1 §9.9 — ~46 status home/away flips in 4 h; nudge cadence ~25 min with 2 transitions each) the settle re-arms continuously, 600 s never elapses, and S10 is permanently held on that zone. During the §9.9 split S10's `_confirmed_on` already rejects (both feeds must name the preset) and the only both-away windows are ha_carrier optimistic-guard windows — the exact source of poisoned snapshots. Starving S10 there is **intended**; the hazard is that it is silent. | **Intended, with a trip-wire.** Stated behavior: a zone subject to a flapping `preset_mode` / `hold_activity` feed will have `last_observed_preset_change` continuously re-stamped and will not run S10 while the flap persists. This is correct (the stale-read window exists irrespective of writer; S10 would also be rejected by `_confirmed_on` under the split). The **discharge** is a code trip-wire (not a soak-watch, per `feedback_no_soak.md`): add a diagnostic attribute `s10_settle_held_s` on the existing per-zone HVAC diagnostics surface (`get_s10_diagnostics()`) carrying `now - zone.last_observed_preset_change` for every rollout zone whose stamp is non-None, AND fire ONE anomaly (existing anomaly dispatcher, not a new NM channel) when any rollout zone's `s10_settle_held_s` has exceeded **`S10_SETTLE_HELD_WARN_S = 14_400`** (4 h) continuously (i.e. the stamp has advanced but never released beyond the threshold for 4 h). The anomaly fires at most once per zone per calendar day, re-arms when the zone goes a full S10 tick without re-arming the stamp. **N = 4 h** justification: covers a full nudge cycle (~25 min × ~9 = ~225 min = ~3.75 h) and two Bryant schedule transitions on zones 2/3 (hourly block) without false-firing on legitimate flap periods, but surfaces a stuck zone before a full operator-day elapses. Rung-1 constant, grep-able, revised in a separate card if post-ship evidence shows ≥10% of rollout days firing it. Within-pass A→B→A flips (one `_async_apply_preset_overrides` tick) are invisible to the observer by construction — the observer runs once per pass. State this plainly in §Problem. Bryant schedule chatter (Q2) is low-rate under `infinite_holds` (observed §5 of state-of-play) and is not expected to trip the warn threshold. |
| R5 | Rev 2 said the fix delays S10 "about 10 min". That understates: S1 writes AFTER `update_all_zones` in the same cycle so an S1 preset change is first OBSERVED on the next tick (+300 s); settle then runs 600 s from the observed timestamp; the `<` comparison against a 300 s interval can need one more tick to clear. | **Stated real latency: ~15-20 min** (900-1200 s). An S10 wire for a preset change at T lands no earlier than `T + 300 s (next-tick observe) + 600 s (settle) ≈ T + 900 s`, and if `T + 900 s` falls between ticks the next S10 opportunity is `T + 1200 s`. This is conservative against the measured 422 s stale window and is the acceptance behavior, not a bug. Live criterion + §Effect updated to say so. |
| R6 | T12 exercises ha_carrier internals (`current_status_activity`) URA tests cannot drive — the test would assert its own mock setup (hollow anchor, Bug Class #62). Oracle left open. Would pass on `develop`. Missing tests: (a) observer wire-in on a live `hass.states` change for both `preset_mode` AND `hold_activity`; (b) R3 boot + unknown flap; (c) R4 trip-wire; (d) mutation anchor for skip-step ORDER (settle before `s1_same_tick`). | **T12 dropped.** The two-path mechanism discrimination moves to the falsifier runbook / post-ship probe (recorder evidence, not a mock). **T15 (observer wire-in — NEW):** build a real `MockHVACZone` whose climate entity is a `hass.states.async_set` target; change the entity's `preset_mode` from `home` → `away` and assert `zone.last_observed_preset_change` advanced AND `_s10_zone_skip_reason` returns `"post_preset_change_settle"`. Repeat with `hold_activity` changing while `preset_mode` is unchanged — the stamp must still fire (R1). **T16 (boot seed — NEW):** fresh `ZoneState` (prev fields = `""`), first readable observation with `preset_mode="home"`, `hold_activity="home"` → `last_observed_preset_change is None`, prev fields = `("home","home")`. Second observation with same values → still None. Third observation flipping to `away` → stamp set. **FAIL on `develop`:** fields don't exist. **T17 (unknown flap — NEW):** prev = `("home","home")`; observation with `preset_mode="unknown"` → prev fields unchanged, no stamp. Next observation `preset_mode="home"` → still no stamp (same as prev). **T18 (trip-wire — NEW):** stamp advanced 10 times across 4 h 1 min, each time 23 min apart → `get_s10_diagnostics()` surfaces `s10_settle_held_s >= 14_400` AND the anomaly dispatcher saw exactly one call for the zone (gate the second call by the once-per-day latch). **FAIL on `develop`:** no diagnostics attribute, no anomaly. **T19 (ordering mutation — NEW):** per-site source mutation — comment out ONLY the `s1_same_tick` check in `_s10_zone_skip_reason`, leave the new settle check in place. Set up BOTH a `_zone_last_s1_write` 60 s ago AND a `last_observed_preset_change` 60 s ago. Assert `_s10_zone_skip_reason` returns `"post_preset_change_settle"` (not None). Restore the file. This proves the settle check is strictly ahead of `s1_same_tick`. **FAIL on `develop`:** neither check exists. **T9 fixed (R2):** record `failures=2, writes=0`, adapter returns `SKIPPED_ALREADY_CORRECT`, after `_s10_success` → `failures=0, writes=0`. **FAIL on `develop`:** `failures` stays 2. T1-T8, T10, T11, T13, T14 unchanged — the Rev 2 re-review confirmed those fail on `develop`. |
| R7 | Rev 2 called the ecobee path a "harmless no-op skip". An option-C select hold flips `preset_of` to `manual` when its settled legs drift; that stamps and DELAYS ecobee S10 storage by the full 15-20 min window. No ecobee zone runs a coordinator today, so impact LOW, but the wording is wrong. | §Non-goals and §Open-questions Q1 updated: on ecobee zones the gate **delays** S10 by `S10_POST_PRESET_CHANGE_SETTLE_S` on any observed preset-of transition (including the option-C select-hold → `manual` flip when its settled legs drift). No ecobee zone is in `hvac_s10_rollout_zone_ids` today so impact is LOW; a future ecobee rollout should re-evaluate the delay against ecobee's own setpoint-settle latency. "Harmless no-op" wording struck. |

---

## Falsifiable invariant (what Rev 3 guarantees)

> **INV-S10-SETTLE:** For any zone `Z` whose readable `(preset_mode, hold_activity)`
> observation transitioned within `S10_POST_PRESET_CHANGE_SETTLE_S` of the current
> cycle time (as recorded on `ZoneState.last_observed_preset_change`), S10 performs
> **zero** of each of: (i) a `strategy.set_preset_range` emission (`site ∈
> {S10_preset_range, S10_preset_range_restore}`); (ii) a `_s10_snapshots[Z][preset]`
> capture; (iii) an increment of `_s10_records[Z][preset|mode].failures`. The next
> S10 wire opportunity is the first full tick ≥ (observed-transition-ts + settle).

> **INV-S10-LATCH-RESET (R2 restated):** For any (Z, preset, mode), a call to
> `_s10_success` — which runs on **`WriteStatus.SKIPPED_ALREADY_CORRECT`** at
> `hvac.py:4707` AND on the limit-matching view path near `hvac.py:4596` — ALSO
> resets `rec["failures"] = 0`. APPLIED (`hvac.py:4686-4704`) is a wire return and
> does NOT reset failures (operator ruling A4 preserved). A rare transient local-raise
> can therefore accumulate across preset segments only if it never alternates with a
> confirmed success; the alternating-raise/APPLIED defeat path is accepted and
> covered by the limit-view not_sticking latch at :4590.

> **INV-S10-SETTLE-OBSERVABLE (R4 discharge):** For any rollout zone `Z` whose
> `last_observed_preset_change` has been continuously < `S10_POST_PRESET_CHANGE_SETTLE_S`
> stale (re-armed before expiring) for ≥ `S10_SETTLE_HELD_WARN_S`, exactly one
> anomaly fires per calendar day with `type="s10_settle_held", zone_id=Z`.

Falsifiers (any reachable path):
1. A `set_activity_setpoint` call at site `S10_*` for Z whose
   `ts_issued − zone.last_observed_preset_change <
   S10_POST_PRESET_CHANGE_SETTLE_S`.
2. A snapshot capture at `hvac.py:4541-4544` for (Z, preset) under the same window.
3. A failure increment at `hvac.py:4714` under the same window.
4. A record with `failures > 0` after `_s10_success` has run on it.
5. A rollout zone held in settle > 4 h without an anomaly.

---

## Chosen fix shape — operator shape **(a) + (b)**, with (b) using an OBSERVED anchor on `ZoneState`

Rev 2's decomposition stands (simplest-only (a) does not cover snapshot poisoning;
simplest-only (b) does not cover the alternating-raise latch creep; (a) + (b)
together close both for one extra assignment + one observer + one constant + one
skip-step + one trip-wire). The only shape change in Rev 3 is R1: the observed
anchor lives on `ZoneState`, not on the coordinator — one dataclass extension and
two new field reads in `update_zone_climate_state`, no coordinator back-reference.

### Why **600 s** (unchanged from Rev 2)

- Observed staleness in the one measured incident: **422 s**.
- A single full periodic tick is 300 s; a window < 300 s is useless by construction.
- `SUPPRESS_TTL_SECONDS_PRESET` (120 s) is unrelated semantics (arrester echo
  suppression); coupling them was Rev 1's F7 error.
- 600 s = 422 s observed + ~180 s margin for next-tick jitter + Carrier's
  status-refresh variance (§5 state-of-play).
- Q3 revisit criteria unchanged.
- Numbers-get-knobs: Rung 1 (module constant). Carrier API read-staleness bound;
  change requires review.

### Why N = **4 h** for the trip-wire (R4 justification)

- Covers one full nudge cycle (~25 min × ~9 transitions ≈ 3.75 h) + two Bryant
  schedule block transitions (hourly) without false-firing on legitimate flapping
  windows (zones with nudges + a working schedule).
- Shorter (e.g. 1 h) would fire routinely on healthy nudge chatter; longer (e.g.
  12 h) would let a silent zone-held-all-day go unobserved.
- Rung 1 (module constant, `S10_SETTLE_HELD_WARN_S = 14_400`), grep-able; revisit
  by card after one week of post-ship observation if ≥10% of rollout days fire
  the anomaly.

---

## Institutional context verified (Rev 3)

### Code locations surveyed (end-to-end, re-verified against `develop @ 05314a3c4`)

- `custom_components/universal_room_automation/domain_coordinators/hvac.py`
  - S10 surface: `_async_apply_preset_overrides` (`:4173`), `_s10_pass` (`:4439`),
    `_s10_zone_skip_reason` (`:4364`), `_s10_desired` (`:4409`),
    `_s10_write_one` (`:4521`), `_s10_original_differs` (`:4738`),
    `_s10_success` (`:4766-4794`), APPLIED record step at `:4686-4704`,
    SKIPPED_ALREADY_CORRECT branch at `:4707`, limit-view success near `:4596`,
    FAILED/`emit_raised` increment at `:4713-4722`, latch at `:4719`.
  - `_zone_last_s1_write` surface: declared `:631`; writer `:3929-3933`; cycle
    seed consumer `:2258-2261`; away-edge consumer `:5594`.
  - Boot refresh of zone climate states: `:1555` (moves `preset_mode` off `""`).
  - **§9.7 → §9.9 stale code-comment references:** `hvac.py` ~3938 and ~5593.
- `custom_components/universal_room_automation/domain_coordinators/hvac_zones.py`
  - `ZoneState` dataclass: `:127-179` (fields target: three new fields immediately
    after the current/target block ending `:143`).
  - `ZoneManager.__init__`: `:279` (NO coordinator reference — this is why Rev 3
    keeps the stamp on `ZoneState`, R1).
  - `update_zone_climate_state`: `:651-670` (observer target; `hold_activity`
    is NOT read today — verified `grep hold_activity hvac_zones.py` = 0).
  - `unavailable` early return: `:658` (preserves prev copy — correct under R3).
- `custom_components/universal_room_automation/domain_coordinators/hvac_strategy.py`
  — `GenericStrategy.set_preset_range` (`:543`); `CarrierStrategy._confirmed_on`
  (`:654`); `preset_range_original` (`:666`); `set_preset_range` (`:692`);
  `preset_of_for` (adapter projection used at `hvac_zones.py:666`).
- `custom_components/universal_room_automation/domain_coordinators/hvac_const.py`
  — S10 constants `:1566`-`:1594`; `S10_PRESET_RANGE_UNCONFIRMED_LIMIT` for the
  latch at `_s10_latch`.
- **Upstream (ha_carrier) referenced for mechanism only, not modified:**
  `carrier_api/climate.py:222-240`, `climate.py:551-553`, `carrier_api/config.py:197-218`.

### Design docs read COMPLETELY

- `docs/Coordinator/HVAC_ARCHITECTURE_STATE_OF_PLAY.md` — mandatory, re-read
  after commit `1480811ba`. §4.2 S10 row carries the UNVERIFIED mechanism marker;
  §5 Carrier status-vs-config feed is the mechanism anchor; §9.9 is the Zone 1
  away feed-split (R4 context); §10 corrections ledger C37 is the Rev 1 → Rev 2
  record. Rev 3 does not require a state-of-play edit — the Rev 2 wording
  (UNVERIFIED mechanism, two reachable paths) still describes the deployed
  surface correctly.
- `docs/Coordinator/IDENTITY_FUSION_CAMERAS_MANUAL.md` — not applicable.

### Prior-art scan (REUSE vs NEW) — Rev 3 revisions

| Proposal | Verdict | Where / why |
|---|---|---|
| Per-zone **observed-preset-change** timestamp on `ZoneState` | **NEW (minimal)** | Three fields added to the existing `ZoneState` dataclass at `hvac_zones.py:127-143` — no coordinator map, no back-reference (R1). Written in `update_zone_climate_state` next to the existing `preset_mode` read. `hold_activity` is read as the raw climate attribute (brand-neutral, Generic/ecobee return `""` and are sentinel-skipped). |
| Settle window constant `S10_POST_PRESET_CHANGE_SETTLE_S` | **NEW** | Rung 1 in `hvac_const.py`, default **600 s**, NOT aliased to `SUPPRESS_TTL_SECONDS_PRESET` (F7). |
| Trip-wire constant `S10_SETTLE_HELD_WARN_S` | **NEW (R4)** | Rung 1 in `hvac_const.py`, default **14_400 s (4 h)**. Discharges the suppression per `feedback_suppression_needs_discharge.md`. |
| Skip-matrix step `post_preset_change_settle` | **NEW** | Returned by `_s10_zone_skip_reason`, inserted **after step 0.5 `climate_unreadable` and BEFORE step 3 `s1_same_tick`** so the OBSERVED gate strictly dominates the shorter S1-only gate. T19 proves the ordering by source mutation (R6). |
| Reset `rec["failures"] = 0` on `_s10_success` | **NEW (shape (a), R2)** | ONE additional line at `hvac.py:4779` next to `rec["writes"] = 0`. Runs on `SKIPPED_ALREADY_CORRECT` (:4707) AND limit-matching view (near :4596) — NOT on APPLIED. Operator ruling A4 preserved. |
| Diagnostic surface `s10_settle_held_s` + once-per-day anomaly | **REUSE (R4)** | Extend existing `get_s10_diagnostics()` with the field; dispatch through the existing anomaly bus (new `type="s10_settle_held"`), no new NM channel. |
| Snapshot-capture gate under settle | **REUSE (D1 covers it)** | Skip-matrix short-circuits `_s10_pass` for the whole tick; step 9 (`:4536-4544`) unreachable while settle is armed. |
| Operator-tunable knob | **REJECTED** | Rung-1 per Numbers-Get-Knobs; change requires review. |

### Prior planning docs consulted

- `docs/planning/PLANNING_hvac_enable_custom_preset_ranges.md` REV 5: §3.2 skip
  matrix (steps 0.5-5) and §6.2 rate/latch model.
- `docs/planning/PLANNING_hvac_w1c_p2_ecobee.md`: ecobee stores URA-side ranges;
  Rev 3 gate **delays** (not "no-ops") an ecobee S10 pass on an option-C select
  hold → `manual` flip (R7). No ecobee zone is in rollout.

### Memory bodies pulled

- `feedback_measure_before_build.md` — gated this whole arc.
- `feedback_marginal_benefit_pushback.md` — (a) + (b) decomposition stands.
- `feedback_suppression_needs_discharge.md` — forces the R4 trip-wire.
- `feedback_hollow_test_anchors.md` — forces T19 source-mutation, forces T12 drop.
- `feedback_wire_in_anchor_mandatory.md` — forces T15 (observer wire-in).
- `feedback_tier2plus_prior_art_scan.md`, `feedback_config_first_before_code.md`,
  `feedback_falsify_before_asserting.md`,
  `feedback_coincidental_equality_masks_concept_split.md` (F7),
  `feedback_no_soak.md` (R4 trip-wire not soak watch) all applied.

### Config-first ruling (unchanged)

No live knob fixes this. `S10_PRESET_RANGE_MIN_SPACING_S` = 600 s and
`S10_PRESET_RANGE_MIN_INTERVAL_S` = 7800 s address rate / latch, not post-write
read-staleness.

---

## Problem (verified from code + 2026-10-15 probe — PARTIAL mechanism, n=1)

**Producer.** `CarrierStrategy.preset_range_original` (`hvac_strategy.py:666-680`)
reads `obs.target_low` / `obs.target_high` off the climate entity. Per §5 of the
state-of-play, HA's `target_temp_{low,high}` come from `_current_activity()`
(`ha_carrier/climate.py:222-230`); when `_current_activity()` returns None, HA
falls back to `_status_zone`. `async_set_activity_setpoint`
(`ha_carrier/climate.py:551-553`) raises `HomeAssistantError("Current activity
unavailable")` under the same None condition. `current_status_activity()`
(`carrier_api/config.py:197-218`) returns None on type / `api_id` mismatch
between status and config.

**Consumer.** `_s10_write_one` (`hvac.py:4521`) calls
`strategy.preset_range_original` at step 9 (`:4537`) to capture a snapshot, and
again just before the wire call (`:4637`) as a no-await re-check. Both reads
pass through `_current_activity()`.

**Effect (revised per probe).** On the first *full periodic* tick after a preset
change (300 s + jitter), S10 reaches `_s10_write_one`. If the Carrier
post-transition window has not closed, two reachable outcomes (both UNVERIFIED):

1. **Stale legs + landed write** (hypothesised, not demonstrated).
2. **Unresolvable activity + rejected write** (observed on 2026-10-14; n=1).

**Harm (expanded per F4).**

1. **Failure-counter latch.** Three consecutive transient local-raises *across
   preset segments* accumulate to `S10_PRESET_RANGE_UNCONFIRMED_LIMIT = 3`
   → `call_failed` + NM; S10 stops managing. Live store at probe:
   `zone_3 away|apply failures: 1`. Under Rev 3, failures reset only on a
   CONFIRMED success (SKIPPED_ALREADY_CORRECT or limit-matching view) —
   operator ruling A4 preserved.
2. **Snapshot poisoning.** First-ever visit to a (zone, preset) during the
   staleness window persists the PREVIOUS preset's range as this preset's device
   original (`hvac.py:4536-4544`, no overwrite). Reachable on zones 1 + 2 at
   CPR rollout.
3. **False drift signal.** FAILED/`emit_raised` rows carry `wire_ok=false`,
   dashboards see adapter drift.

**Within-pass invisibility (R4).** The observer runs once per
`_async_apply_preset_overrides` tick; an A→B→A flip inside one pass is invisible.
Accepted — S10 only runs on full ticks, and the staleness window is scoped to
*observed* transitions.

**Base rate: 1 / 544** zone_3 preset segments since 2026-10-01. Rare, but the
3-strike cumulative latch does not need frequency — it needs persistence.

---

## Deliverables

### D1 — Per-zone post-observed-preset-change S10 settle (shape (b))

**Change 1 (ZoneState fields, NEW).** In `hvac_zones.py:127-143`, add to the
`ZoneState` dataclass immediately after the current/target block (:143):

```python
# S10 observed-preset-change observer (R1):
# brand-neutral prev copies for the stamp decision. "" and "unknown"
# are treated as unreadable (R3): neither updates the prev copy nor
# stamps. First readable observation seeds without stamping.
prev_preset_mode: str = ""
prev_hold_activity: str = ""
last_observed_preset_change: datetime | None = None
```

**Change 2 (observer wire-in, in `update_zone_climate_state`).** At
`hvac_zones.py:651-670`, after the existing `zone.preset_mode = preset_of_for(...)`
at :666, add the raw `hold_activity` read and the stamp decision:

```python
new_preset = zone.preset_mode  # already W1-C P2 projected
new_hold = state.attributes.get("hold_activity", "") or ""
_UNREADABLE = ("", "unknown")
if new_preset not in _UNREADABLE and new_hold not in _UNREADABLE:
    if zone.prev_preset_mode == "" and zone.prev_hold_activity == "":
        # First readable observation — seed, do not stamp (R3).
        zone.prev_preset_mode = new_preset
        zone.prev_hold_activity = new_hold
    elif (new_preset != zone.prev_preset_mode
          or new_hold != zone.prev_hold_activity):
        zone.last_observed_preset_change = dt_util.utcnow()
        zone.prev_preset_mode = new_preset
        zone.prev_hold_activity = new_hold
# else: unreadable observation — leave prev / stamp untouched (R3).
```

RAM-only; survives config-entry reload only because `ZoneManager` is re-created
(same lifecycle as `_hvac_armed`). Boot/reload = fields at dataclass defaults
(correct: no settle until a readable transition).

**Change 3 (skip-matrix step, additive).** Extend `_s10_zone_skip_reason`
(`hvac.py:4364`) with a NEW check inserted **after step 0.5 `climate_unreadable`
and BEFORE step 3 `s1_same_tick`**: return `"post_preset_change_settle"` when
`zone.last_observed_preset_change is not None` AND `(now - zone.last_observed_preset_change)
< timedelta(seconds=S10_POST_PRESET_CHANGE_SETTLE_S)`. Fail-closed on exception
(treat as settle). The pre-call re-check at `_s10_write_one:4664` already re-runs
the full skip matrix, so the gate catches a settle armed during the write-ahead
save await. T19 (source mutation) is the regression anchor for the ordering vs.
`s1_same_tick`.

**Change 4 (new constants) in `hvac_const.py`:**

```python
# S10 defers for one Carrier post-write staleness window after any
# OBSERVED (preset_mode | hold_activity) transition on the zone
# (any writer: S1, arrester, S7 restore, AC-reset, egress, excursion,
# S11/S13, human, Bryant schedule). Prevents a stale status-feed read
# of target_low/high AND the matching unresolvable-activity local
# raise from driving a redundant or doomed set_preset_range AND from
# poisoning a first-visit snapshot. NOT the same semantic as
# SUPPRESS_TTL_SECONDS_PRESET (arrester echo on URA's own writes);
# do not couple them. Rung 1 — measured against the 2026-10-14
# incident (422 s stale window).
S10_POST_PRESET_CHANGE_SETTLE_S: Final = 600  # seconds

# R4 discharge: a rollout zone whose observed-preset-change stamp has
# been continuously < S10_POST_PRESET_CHANGE_SETTLE_S stale for this
# long trips an anomaly (type="s10_settle_held"), at most once per
# zone per calendar day. Covers a full nudge cycle + two Bryant
# schedule block transitions without false-firing on legitimate flap.
S10_SETTLE_HELD_WARN_S: Final = 14_400  # 4 h
```

**Change 5 (trip-wire).** Extend the existing per-tick `get_s10_diagnostics()`
surface with `s10_settle_held_s` per rollout zone. Add a once-per-day latch
(`_s10_settle_held_fired_on: dict[str, date]` on the coordinator) and dispatch
one anomaly via the existing anomaly bus when a rollout zone exceeds the warn
threshold. The latch clears when the zone goes a full S10 tick without
`last_observed_preset_change` being advanced.

**No new NM channel, no new persisted state.**

### D2 — Reset `rec["failures"] = 0` on CONFIRMED success (shape (a), R2)

**Change.** In `_s10_success` at `hvac.py:4779`, add `rec["failures"] = 0`
immediately after the existing `rec["writes"] = 0`. This path is called ONLY
from (i) the `SKIPPED_ALREADY_CORRECT` branch at `hvac.py:4707` and (ii) the
limit-matching view success path near `hvac.py:4596` — the two sites that
constitute a CONFIRMED success per operator ruling A4. APPLIED at
`hvac.py:4686-4704` does NOT call `_s10_success` and does NOT reset failures
(by design). The record discharges its entire retry budget on confirmation.

### D3 — Code-comment corrections

- `hvac.py` line **~3938**: `§9.7` → `§9.9`.
- `hvac.py` line **~5593**: `§9.7` → `§9.9`.

If Review A/B/C identify a residual wording issue in state-of-play §4.2 or §10
C37 that misaligns with Rev 3, patch it in the same build commit.

### Non-goals (explicit)

- No change to adapter verbs.
- No change to `_zone_last_s1_write` or any of its consumers.
- No change to `_zones_written_this_cycle` seeding at `hvac.py:2258-2261`.
- **No ecobee adapter change** — gate **delays** S10 on an ecobee option-C
  select-hold flip; no ecobee zone is in rollout today (R7).
- No persistence-schema change (`_s10_snapshots`, `_s10_records`,
  `.storage/universal_room_automation.hvac_zone_state` all untouched).
- No new NM channel; the anomaly rides the existing bus.
- No fast-path change.

---

## Acceptance criteria (each test FAILS on today's `develop`)

### Discriminating assertions (per F6)

Each unit test is written so its assertions distinguish the fix from the no-op
baseline. A test whose assertions pass on `develop` is a hollow anchor and MUST
be rewritten.

### Unit (`quality/tests/hvac/test_s10_post_preset_change_settle.py`, NEW)

- **T1 (D1 — gate active):** `zone.last_observed_preset_change = now - 300 s`;
  `_s10_zone_skip_reason` returns `"post_preset_change_settle"`. **FAIL on
  `develop`:** no such branch.
- **T2 (D1 — gate expired):** `zone.last_observed_preset_change = now - 601 s`;
  returns None or any other reason, NOT `"post_preset_change_settle"`.
- **T3 (D1 — zero wire + zero capture):** gate active; `_s10_pass(mode="apply")`
  emits zero `strategy.set_preset_range` calls, writes zero `climate_write`
  rows, no `_s10_snapshots[zone_id][preset]` entry, no
  `_s10_records[zone_id][preset|apply]` entry. **FAIL on `develop`:** apply pass
  reaches step 9 + captures.
- **T4 (D1 — restore mode):** gate active, snapshot exists; `_s10_pass(mode=
  "restore")` emits zero `strategy.set_preset_range` calls.
- **T5 (D1 — pre-call re-check):** stamp armed between pass-level skip check
  (:4467) and pre-call re-check (:4664); pre-call `_stand_down` is
  `"post_preset_change_settle"`.
- **T6 (D1 — sibling zone unaffected):** gate active on zone_3; zone_1 (no
  stamp) proceeds normally.
- **T7 (D1 — boot with no stamp):** `zone.last_observed_preset_change is None`;
  `_s10_zone_skip_reason` behaves identically to today for every zone.
- **T8 (D1 — observed anchor covers non-S1 writer):** stamp written by
  simulating the arrester's revert path (set the stamp via a direct
  `update_zone_climate_state` run with the preset flipped in `hass.states`);
  gate fires without `_zone_last_s1_write` being set. **FAIL on `develop`:**
  no field, no gate.
- **T9 (D2 — failure reset on SKIPPED_ALREADY_CORRECT, R2):** record
  `failures=2, writes=0`, value stays V1, adapter returns
  `SKIPPED_ALREADY_CORRECT`; after `_s10_success` → `failures=0, writes=0`.
  **FAIL on `develop`:** `failures` stays 2.
- **T10 (D2 — failure reset on limit-matching view, R2):** limit-view path
  near `:4596` matches the device value; `_s10_success` runs; `failures=0`
  after. **FAIL on `develop`:** `failures` unchanged.
- **T11 (D2 — three transient raises WITHOUT D2 would latch, APPLIED between
  does NOT reset):** on `develop`-with-D1-only, three FAILED/`emit_raised` with
  APPLIED between (NOT SKIPPED_ALREADY_CORRECT, per R2) → record latches.
  With D1 + D2 enabled AND the APPLIED is a wire return, failures still
  accumulate (A4 preserved); only a SKIPPED_ALREADY_CORRECT or limit-view match
  resets. **FAIL on `develop`:** no settle gate on the raises — the three
  raises happen on consecutive ticks and latch.
- (Rev 2 T12 DROPPED per R6 — ha_carrier internals cannot be driven from URA
  tests; mechanism discrimination moves to the falsifier runbook as a recorder
  probe.)
- **T13 (integration, unchanged):** full `_async_apply_preset_overrides` with a
  simulated observed preset transition at `now - 60 s`; no `climate_write` row
  at `site=S10_preset_range` for the zone; next cycle at `now + 540 s` emits
  normally.
- **T14 (integration, unchanged):** switch OFF → restore pass; gate active →
  zero restore wire calls; gate expired → restore proceeds (snapshot still
  correct).
- **T15 (observer wire-in, NEW R6a):** `MockHVACZone` with a `hass.states.async_set`
  target entity. Change `preset_mode` from `home` → `away` with `hold_activity`
  constant; call `update_zone_climate_state(zone_id)`; assert
  `zone.last_observed_preset_change` advanced AND `_s10_zone_skip_reason` returns
  `"post_preset_change_settle"`. Then test the mirror: `preset_mode` constant,
  `hold_activity` changing; stamp must still fire (R1). **FAIL on `develop`:**
  fields do not exist.
- **T16 (boot seed, NEW R6b / R3):** fresh `ZoneState`; first readable observation
  `(preset_mode="home", hold_activity="home")` → `last_observed_preset_change is
  None`, prev fields = `("home", "home")`. Second observation same → still None.
  Third observation `(preset_mode="away", hold_activity="away")` → stamp set.
  **FAIL on `develop`:** fields do not exist.
- **T17 (unknown flap, NEW R6b / R3):** prev = `("home", "home")`; observation
  with `preset_mode="unknown"` → prev unchanged, no stamp. Follow-up observation
  `preset_mode="home"` → still no stamp. **FAIL on `develop`:** fields do not
  exist.
- **T18 (trip-wire, NEW R6c / R4):** advance `zone.last_observed_preset_change`
  10 times at 23-min intervals across 4 h 1 min (each re-stamp within 600 s of
  the previous); `get_s10_diagnostics()` surfaces `s10_settle_held_s >=
  14_400`; the anomaly dispatcher recorded exactly one call with
  `type="s10_settle_held"` for the zone; a second cross of the threshold on the
  same calendar day does NOT fire. **FAIL on `develop`:** no diagnostics field,
  no anomaly.
- **T19 (skip-step ordering mutation, NEW R6d):** per-site source mutation —
  comment out ONLY the `s1_same_tick` check in `_s10_zone_skip_reason`, leave
  the settle check in place. Set up BOTH a `_zone_last_s1_write = now - 60 s`
  AND `zone.last_observed_preset_change = now - 60 s`. Assert
  `_s10_zone_skip_reason` returns `"post_preset_change_settle"`. Restore the
  file. **FAIL on `develop`:** neither check exists.

### Sensor / outcome map

- `get_s10_diagnostics()` outcome map carries
  `{status: "skipped", reason: "post_preset_change_settle"}` for a settled tick
  on an eligible zone, AND an `s10_settle_held_s` per rollout zone whose stamp
  is non-None.

### Baseline + post-ship probe

Pre-ship baseline SQL unchanged from Rev 2 (F8 corrected). On zone_3 post-ship
the ratio (S10 writes / preset changes) should drop; S10 FAILED/`emit_raised`
rows should be zero. On zones 1 + 2 (if rolled out in the same window), the
ratio should be ≤ 1 and no FAILED rows.

### Live

- On `develop` restart, within one full S1 cycle a preset change on zone_3
  produces NO `climate_write` with `site="S10_preset_range"` for ≥ 600 s
  measured from the OBSERVED transition timestamp. **The effective delay from
  the S1 write to the next S10 wire opportunity is ~15-20 min** (R5):
  `+300 s next-tick observe + 600 s settle + up to 300 s to next tick`.
- Latch store: after any CONFIRMED success (SKIPPED_ALREADY_CORRECT or
  limit-matching view) on a record with `failures > 0`, next persist shows
  `failures=0`. An APPLIED alone does NOT reset `failures` (A4).
- Trip-wire: no rollout zone reports `s10_settle_held_s >= 14_400` under
  normal operation; if one does, exactly one anomaly surfaces per zone per day.

### Falsifier runbook (per `feedback_falsify_before_asserting.md`)

The acceptance observation that would REFUTE the fix: any `climate_write` row
within `[observed_transition_ts, observed_transition_ts + S10_POST_PRESET_CHANGE_SETTLE_S]`
for the same zone with `site LIKE 'S10_%'`. The post-ship probe surfaces it
directly. Mechanism discrimination between "stale legs + landed write" and
"unresolvable activity + rejected write" is harvested from
`ha_carrier`-side logs post-restart (not from a URA test mock) — Review C
decides whether a second occurrence is required before sign-off.

---

## Review tier + framings

**Tier 2-DB (operator-elevated).** Per the Rev 2 re-review R7, placing the
stamp on `ZoneState` (R1) reduces the ripple vs. a coordinator back-reference,
but D1 still introduces: a new per-tick observer in a shared primitive
(`update_zone_climate_state`), a new skip-step inserted ahead of the pre-existing
S1 same-tick gate, a new diagnostics attribute, and a new anomaly type.
D2 changes failure-counter semantics on the confirmed-success path only.
Mechanism remains PARTIAL (n=1).

Three framing-disjoint reviews **in parallel**:

- **Review A — correctness + edge cases.** Settle predicate; sentinel handling
  (`""`, `"unknown"`, `"unavailable"` early return); skip-matrix ordering (T19
  mutation anchor is the oracle); observer behaviour when `preset_mode` and
  `hold_activity` disagree mid-transition; pre-call re-check path; D2 reset on
  SKIPPED_ALREADY_CORRECT + limit-matching view ONLY (NOT APPLIED) — including
  no clobber of `_s10_latch` / `_s10_note_outcome` / diagnostics consumers;
  ecobee delay path (R7); D-LOW-2 generation guard still correct;
  `_s10_settle_held_fired_on` latch clear criterion is correct.
- **Review B — cross-coordinator + lifecycle + migration integrity.** Boot
  with default fields (no stamp, no S10 hold); seed-vs-stamp rule on first
  readable observation (R3); a transition observed mid-await (settle arms,
  pre-call re-check at :4664 catches it); user toggle of switch 01 during
  settle; interaction with the arrester's own `SUPPRESS_TTL_SECONDS_PRESET`
  (deliberately not shared); Bryant schedule flipping a preset on zones 2/3
  (should NOT trip the warn threshold under `infinite_holds`); migration: no
  persisted state change — existing latch-store rows with `failures > 0`
  discharge correctly on the first post-upgrade CONFIRMED success (not
  retroactively latched); no double-dispatch of `preset_change` ledger rows;
  anomaly bus wiring (type routing, once-per-day latch, latch clear).
- **Review C — new surfaces + test fixture authority + adversarial
  completeness.** Verify every acceptance test fails on `develop` (per-site
  source mutation, not aggregate monkeypatch); verify T15 drives
  `update_zone_climate_state` via real `hass.states` changes (wire-in anchor);
  verify T19 restores the file; re-enumerate every S10 wire site AND every
  writer that mutates `preset_mode` / `hold_activity` on a Carrier zone
  (independent of the plan's list); state the falsifiable invariants in own
  words and attempt to break INV-S10-SETTLE, INV-S10-LATCH-RESET,
  INV-S10-SETTLE-OBSERVABLE from any reachable path including pre-existing
  code; verify `get_s10_diagnostics()` round-trips the new outcome row AND
  `s10_settle_held_s`.

**Plan review (per CLAUDE.md Tier-2+ plan-review protocol).** Rev 3 is the
response to the Rev 2 plan re-review; ONE adversarial plan review of Rev 3 is
required before build dispatch.

---

## Doc corrections required (apply in same commit as build)

The state-of-play corrections from Rev 1 shipped in commit `1480811ba`.
Remaining items for this cycle:

1. **`hvac.py` ~line 3938 comment:** `§9.7` → `§9.9`.
2. **`hvac.py` ~line 5593 docstring:** `§9.7` → `§9.9`.
3. If Review A/B/C find a wording residual in state-of-play §4.2 or §10 C37
   after Rev 3 approval, patch in the same build commit.

---

## Open questions

- **Q1 — ecobee interaction (R7).** The ecobee adapter stores URA-side ranges;
  Rev 3's gate **delays** (not "no-ops") an ecobee S10 pass on an option-C
  select-hold flip (`preset_of` → `manual` on settled-leg drift). No ecobee
  zone is in rollout today. If an ecobee rollout is scheduled, re-evaluate
  600 s vs. ecobee's own setpoint-settle latency.
- **Q2 — Bryant schedule-driven transitions on zones 2/3.** Observer arms the
  settle on any observed transition. Under `infinite_holds` (§5 state-of-play)
  schedule chatter is low-rate and is NOT expected to trip the 4 h warn.
  Review B confirms.
- **Q3 — Window length revisit.** 600 s is n=1 + jitter margin. Post-ship
  probe criteria unchanged from Rev 2: raise to 900 s if p99 stale-window ≥
  500 s across ≥ 10 preset changes; drop to 450 s if p99 < 300 s across ≥ 50.
- **Q4 — AC-reset preset writes.** Covered by the observed anchor (any observed
  `preset_mode` / `hold_activity` change arms).
- **Q5 — Trip-wire threshold revisit (R4).** `S10_SETTLE_HELD_WARN_S = 14_400`
  (4 h) is first-pass; revisit by card after one week post-ship if ≥10% of
  rollout days fire the anomaly.

---

## Build sequence (for the builder, not this cycle)

1. Add `S10_POST_PRESET_CHANGE_SETTLE_S = 600` and `S10_SETTLE_HELD_WARN_S =
   14_400` to `hvac_const.py` with the comment blocks above.
2. Add three new fields to the `ZoneState` dataclass at `hvac_zones.py:127-143`:
   `prev_preset_mode: str = ""`, `prev_hold_activity: str = ""`,
   `last_observed_preset_change: datetime | None = None`.
3. In `hvac_zones.ZoneManager.update_zone_climate_state` (`:651-670`),
   immediately after the existing `preset_mode` read at :666, add the
   `hold_activity` read and the sentinel-aware seed/stamp block (Change 2 above).
4. Extend `_s10_zone_skip_reason` with `post_preset_change_settle` inserted
   between step 0.5 and step 3 (`s1_same_tick`); fail-closed on exception.
5. In `_s10_success` (`hvac.py:4779`), add `rec["failures"] = 0` next to
   `rec["writes"] = 0`.
6. Add `_s10_settle_held_fired_on: dict[str, date] = {}` to `HVACCoordinator`
   init; extend `get_s10_diagnostics()` with `s10_settle_held_s`; dispatch one
   anomaly `type="s10_settle_held"` on cross of `S10_SETTLE_HELD_WARN_S` with
   once-per-day latch and clear-on-release.
7. Patch the two §9.7 → §9.9 code-comment references.
8. Add unit tests in `quality/tests/hvac/test_s10_post_preset_change_settle.py`
   (T1-T11, T13-T19; T12 dropped).
9. Run `.venv-ha/bin/python -m pytest quality/tests/hvac/ -k "s10 or
   preset_range or preset_change or settle" -v`.
10. Run the baseline probe SQL on `develop` immediately before deploy; stash
    the result in the README. Re-run 7 and 14 days post-restart; record both
    in the README validation table.

---

## Report (for the parent orchestrator)

- **Chosen shape:** operator shape **(a) + (b)**. (b) D1 observed-preset-change
  settle gate (600 s, OWN constant, stamp on `ZoneState`, R1); (a) D2 reset
  `failures` on CONFIRMED success (R2, option (i) — operator ruling A4
  preserved).
- **Tier:** **Tier 2-DB (operator-elevated)** — ripple into zone-state observer
  + confirmed-success semantics + diagnostics + anomaly bus; mechanism PARTIAL
  (n=1). Three framing-disjoint reviews (A=correctness, B=cross-coord+
  lifecycle+migration, C=new-surfaces+test-authority+adversarial-completeness)
  in parallel + a Rev-3 plan review before build dispatch.
- **Invariants:** **INV-S10-SETTLE** + **INV-S10-LATCH-RESET** (R2 restated:
  SKIPPED_ALREADY_CORRECT or limit-matching view ONLY) + **INV-S10-SETTLE-OBSERVABLE**
  (R4 trip-wire).
- **Effective delay:** **~15-20 min** from S1 write to next S10 opportunity
  (R5), by design.
- **Mechanism marker:** PARTIAL / UNVERIFIED (n=1). Both reachable paths gated
  by D1. Mechanism discrimination moves to the falsifier runbook (recorder
  probe), T12 dropped (R6).
- **Measurement completed before plan:** yes (2026-10-15 probe).
- **Unresolved / deferred:**
  - **Q3** window-length tuning; **Q5** trip-wire threshold tuning —
    both post-ship, by card.
  - Mechanism remains n=1; Review C may elect to harvest additional
    `ha_carrier` logbook evidence before sign-off.
- **Not changed in this cycle (explicit non-goals):** adapter verbs;
  `_zone_last_s1_write` surface; `_zones_written_this_cycle` seed;
  persistence schema; ecobee adapter (delay only, no code change); NM channel
  surface (anomaly rides existing bus); fast-path.
