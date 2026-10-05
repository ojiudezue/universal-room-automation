# PLANNING — HVAC-COMPOSE-AWAY-THROTTLE-STORM-BLOCKER-1 (F2 compose-away throttle bypass)

**Status:** PLAN REV 1 (2026-10-02). Not built. No code edited by this plan.
**Card:** `HVAC-COMPOSE-AWAY-THROTTLE-STORM-BLOCKER-1` (`kanban.data.yaml:2106`). Parent `HVAC-CUSTOM-PRESET-RANGES-1` (`:30212`, Batch C). Siblings `HVAC-S10-DPM-VS-S1-1` (`:1727`), `HVAC-RESTORE-WRITERS-STRAND-EMPTY-NIGHT-ZONE-1` (`:2132`).
**Arc position:** `HVAC_ARCHITECTURE_STATE_OF_PLAY.md` §3.3 (D9 dormant, blocked on this card), §9.7 (first), §11 row 5.

---

## 0. Verdict up front — DO NOT BUILD STANDALONE. This card is ALREADY FOLDED into the CPR plan by deletion.

The card asks to replace the unconditional F2 bypass with a ground-truth setpoint compare (or S8/S9 cache invalidation). The adjacency sweep found that `PLANNING_hvac_enable_custom_preset_ranges.md` **REV 3.2** (reviewed twice: `plan_review_hvac_cpr_rev3.md` + REV 3.1 re-check) already disposes of this card:

- CPR D3 **deletes** the D9 compose-away block, the F2 bypass, the S10 suppress stamps and the throttle-map write (CPR plan §5 D3 + §8). D3c retires the whole `_last_emitted_range` map (CPR R1).
- CPR §9: "`HVAC-COMPOSE-AWAY-THROTTLE-STORM-BLOCKER-1` → done on ship by D3 DELETION. Evidence: `test_s10_empty_zone_no_storm_12_ticks`; live Q1/Q4/Q5."

The card's text (09-17) predates CPR REV 3 (09-29). Writing a second, different fix would conflict with an approved, reviewed plan for the same lines.

**Why the card's "ground-truth compare" fix would NOT close the storm anyway (marginal-benefit decomposition):**

1. **The sibling fight dominates the volume.** Since W1-B (v5.103.18, §9e), S1 reclaims any `manual` with no gate armed. S10 writes raw `set_temperature` (`hvac.py:4131`), which Carrier turns into a `manual` hold (§5 `climate.py:467-537`). S10 opens no borrow row, so gate (e) does not arm. Next tick S1 pins `away`, then S10 writes again. A ground-truth compare would see the S1-restored away-profile setpoints ≠ D9's cool-7 pair and **still write every tick**. That is why the CPR plan measures the old S10 at ~48 calls/h/empty zone (CPR §6.3), not the card's 12. A compare at the F2 site removes the bypass but not the storm.
2. **No trustworthy "ground truth" exists on Carrier today.** HA setpoints come from the STATUS feed's named activity (§5 `climate.py:230-240`). They can be stale, or masked for up to 5 min by ha_carrier's local post-write guard (C16, C21). Zone_1 shows false `home` setpoints on the status feed for hours (§9.7 second entry). A compare would see a permanent difference there and write every tick. The confirmation oracle is still open (`HVAC-WRITE-CONFIRMATION-ORACLE-1`; C22/C23: neither feed is always right).
3. **The bypass's own rationale is mostly obsolete.** F2 exists because third-writer restores (S8/S9/S11/S13) wrote comfort setpoints without updating `_last_emitted_range`. W1-B D2.4 made those returns presets-only. They write raw setpoints only for a HUMAN_MANUAL snapshot (S8: `hvac_override.py:7255-7276`; S9: `:7746`; S11: `hvac_predict.py:1114`; S13: `hvac_predict.py:1877`). A presets-only return lands on a named preset, and row-1 S1 retreats that preset next tick. The corrector D9 was built to be is no longer needed (CPR §9 by-construction proof).

**Recommendation:** dispose this card as **DUPLICATE → folded into `HVAC-CUSTOM-PRESET-RANGES-1` D3/D3c**. It closes when CPR ships. The acceptance criteria below get added to the CPR build brief verbatim so this card's discriminator is explicitly checked. §6 keeps a standalone fallback design, parked with a revival trigger, in case CPR is abandoned.

---

## 1. Config-first check

| Candidate | Solves it? |
|---|---|
| Leave `switch.ura_hvac_coordinator_guest_mode_actuation` OFF (live: off) | Yes, for today. The storm cannot happen while S10 returns at `hvac.py:3923`. This is the current, correct state and needs no action. |
| Turn the switch on with a lower DPM rate | No. F2 bypasses all throttling, and the S1 fight is per tick. |
| `ha_carrier` options | No. |

**Verdict:** no config change enables D9 safely. Code is needed, and it is the CPR D3 deletion.

---

## 2. Institutional context verified

### 2.1 Prior-art scan — REUSE / BUILD per piece

| Piece | Verdict | Symbol, file:line |
|---|---|---|
| Fix for the F2 bypass | **REUSE the planned deletion** | CPR plan D3 deletes `hvac.py:4096-4111` (now `:4096-4111`, re-verified 2026-10-02) |
| Throttle map | **REUSE the planned retirement** | `_last_emitted_range`: init `hvac.py:667`; reader `hvac.py:4108`; writer `hvac.py:4153`; `hvac_predict.py:932`, `:1003` reads; `:1153` S11 write; `:974` `update_throttle` kwarg; `:482`, `:1260` callers; `:1900-1901` S13 write; **`switch.py:2061-2062`** clear (the CPR plan cites `:2046-2047`, which is stale; builder must re-grep) |
| Ground-truth setpoint read | **REUSE if the fallback is ever built** | `zone.target_temp_low/high` (ZoneState, already read at S8 `hvac_override.py:7270`); `_climate_unreadable` `hvac.py` (~2382, Batch D) |
| Per-zone write spacing | **REUSE pattern** (fallback only) | CPR `S10_PRESET_RANGE_MIN_SPACING_S` design (CPR §6.1) |
| A new "compose-away throttle" mechanism | **NOT BUILT** | Duplicate of CPR D3 |

**Surfaces grepped (2026-10-02, develop working tree):** `_last_emitted_range|compose_away|guest_mode_actuation|throttle` over `custom_components/universal_room_automation/**`; `site="(S8|S9|S11|S13|S10)…"` over `domain_coordinators/`; `S10|compose|_last_emitted_range|CPR` over the W1-C plan.

### 2.2 Prior plans consulted
- `PLANNING_hvac_enable_custom_preset_ranges.md` REV 3.2 — read in full (973 lines). It is the controlling plan and already folds this card.
- `PLANNING_hvac_w1c_thermostat_profiles.md` — skimmed for S10/CPR/`_last_emitted_range` (§2 row A13, §3f merge order, P1 golden equality set).
- `docs/reviews/code-review/plan_review_hvac_cpr_rev3.md` — referenced through the CPR errata; not re-read.

### 2.3 Design docs
- `docs/Coordinator/HVAC_ARCHITECTURE_STATE_OF_PLAY.md` — read completely (589 lines): §2, §3.3, §4.1-4.3, §5, §6, §7, §9.1, §9.7 (both entries), §9e, §10 C1-C29, §11.
- §10 claims are not re-asserted. In particular:
  - `hold_activity` is not used as an oracle (C20, C22, C23).
  - The 5-min guard is not described as a cloud re-send (C21).
  - The `_auto_return` manual-skip is untouched (C26).

### 2.4 Memory
`feedback_adjacency_sweep_before_minting`, `feedback_marginal_benefit_pushback`, `feedback_extend_existing_never_rebuild`, `feedback_config_first_before_code`, `reference_hvac_state_of_play`.

### 2.5 Code read this session
- `hvac.py:3900-4171` (S10 method, whole).
- `hvac_override.py:7250-7280` (S8 HUMAN_MANUAL-only raw restore).
- `switch.py:2040-2064` (switch `is_on` / turn_on / turn_off map clear).
- grep hits listed in §2.1.

---

## 3. Overlap with in-flight work (checked 2026-10-02)

| Branch / work | Touches | Interaction |
|---|---|---|
| **develop (v5.103.23+ Batch B, v5.103.24 Batch D)** | S10 anchors moved about 500 lines (CPR REV 3 table). Batch D added `_climate_unreadable`. | Anchors re-verified above. D9/F2 are byte-unchanged on develop. |
| **`feature/hvac-w1c-p1`** (W1-C P1, `PLANNING_hvac_w1c_thermostat_profiles.md`) | Routes every thermostat write through the profile, **including A13 = S10 `hvac.py:4131`**. The P1 byte-identity golden includes `_last_emitted_range` in the named in-memory equality set (W1-C §P1 "Equality"). | **Hard ordering: W1-C P1 merges FIRST** (W1-C §3f, CPR merges after). CPR D3 then deletes the S10 `emit_set_temperature` call and the map. That makes P1's S10 golden and its `_last_emitted_range` equality obsolete. The CPR build must retire or regenerate those goldens **as an intended behaviour change**, recorded in the build notes. (P1 itself treats golden regeneration as a review-blocking diff, so the reviewer needs to know this one is expected.) Do not start the CPR build on a base without P1. |
| `HVAC-S10-DPM-VS-S1-1` | Same S10 site | Folded into CPR §3.1 (named-profile write). It must ship in the same build. Fixing F2 without it leaves the S1 fight (§0 point 1). |
| `HVAC-RESTORE-WRITERS-STRAND-EMPTY-NIGHT-ZONE-1` | The map's producers and consumers | Closed by construction in CPR D3c (CPR §9). |

---

## 4. Falsifiable invariant (for this card, checked inside the CPR build)

> **INV-NO-STORM.** With switch 01 resolved ON and DPM overrides active, in ANY reachable state, an established, fused-empty zone that stays on the same named preset (home / sleep / away / vacation) gets **zero** S10 wire calls on the second and later ticks once its range matches. Across any 60 min, wire calls for one (zone, preset) are ≤ ⌈3600 / `S10_PRESET_RANGE_MIN_SPACING_S`⌉ + 1 = **7**, independent of DPM flapping, S1 reclaims, borrow returns, or restarts.

It is falsified by any reachable config where a single empty zone gets ≥ 2 S10 calls per 10 min, or where S10 followed by S1 alternates on consecutive ticks. Reviewer D must try these:
- the zone_1 status/hold split (§9.7 second entry);
- a presets-only borrow return landing on `away`;
- a HUMAN_MANUAL S8 raw restore on an empty zone;
- a DPM `cool_high` flapping every tick;
- 8 restarts within an hour.

---

## 5. Emission sites (every site that bears on the storm)

| Site | file:line (develop 2026-10-02) | Role | After CPR |
|---|---|---|---|
| S10 compose-away selector | `hvac.py:4051-4061` | picks `away` for an established-empty zone | DELETED (CPR D3) |
| S10 transient hold | `hvac.py:4031-4050` | skips a transient-blocked empty zone | DELETED |
| S10 cool-7 baseline | `hvac.py:4074-4075` | low = cool − 7 | DELETED (low = configured heat) |
| **F2 bypass** | **`hvac.py:4108-4111`** (`if last == resolved_pair and not _compose_away`) | the card's defect | DELETED |
| S10 suppress / unsuppress | `hvac.py:4114-4115`, `:4150-4151`, `:4168` | arrester echo masking | DELETED (M4) |
| **S10 wire call** | **`hvac.py:4131-4142`** `emit_set_temperature(site="S10_dpm_apply")` | the storm's only emitter | REPLACED by `emit_set_activity_setpoint` via `CarrierStrategy.set_preset_range` |
| Throttle-map write | `hvac.py:4153` | | DELETED |
| S1 preset (reclaims S10's manual) | `hvac.py` S1 site (`Strategy.hold_preset`) | the second half of the fight | unchanged; CPR's named-profile write gives it nothing to reclaim |
| Third writers that motivated F2 (raw only on HUMAN_MANUAL) | S8 `hvac_override.py:7267-7276`; S9 `:7746`; S11 `hvac_predict.py:1114` (+ map write `:1153`); S13 `hvac_predict.py:1877` (+ map write `:1900-1901`) | | map writes DELETED (D3c); raw HUMAN_MANUAL restores unchanged |
| Map clear on switch OFF | `switch.py:2061-2062` | | DELETED (D3c) |
| Map readers | `hvac_predict.py:932`, `:1003` | | DELETED (D3c) |

There are no other `set_temperature` emitters on the S10 path. The W1-A AST lint `test_hvac_climate_write_funnel_completeness.py` enforces the funnel.

---

## 6. Standalone fallback design — PARKED

**Revival trigger:** the operator drops or indefinitely defers CPR, but wants D9 compose-away (raw-setpoint retreat) enabled anyway.

If that happens:

- **(a)** Replace the F2 bypass with a ground-truth compare. Skip unless `|zone.target_temp_low − emit_low| > 0.5 or |zone.target_temp_high − emit_high| > 0.5`.
- **(b)** Add a per-zone minimum spacing for S10: a new rung-1 constant `S10_COMPOSE_AWAY_MIN_SPACING_S = 600`. Rung 1 because it is a cloud call-rate bound and changing it should require review, mirroring the reasoning for CPR F4. This bounds the zone_1 false-status case.
- **(c)** **Still required:** resolve `HVAC-S10-DPM-VS-S1-1` (S1 fight) first. Without it, (a)+(b) only cap the storm at about 6+6 writes/h/zone; they do not remove it.

**Tier for the fallback:** Tier 2-DB (regression-prone, cross-coordinator S1 ↔ S10). Not recommended. The CPR path is strictly better on every axis.

---

## 7. Deliverables (inside the CPR build; no standalone deliverable)

### D1 — Card acceptance carried into the CPR build brief
Add to the CPR builder brief verbatim. No new code beyond CPR D3/D3c.

#### Acceptance criteria
- **Test:** `test_s10_empty_zone_no_storm_12_ticks` (CPR D3). An established, fused-empty zone on `away` with switch ON and an active DPM override gets ≤ 1 S10 wire call over 12 ticks.
- **Test (new, discriminating):** `test_s10_no_s1_alternation_on_empty_zone`. Drive `_apply_house_state_presets` for 6 ticks on an empty zone with real `PresetManager` + S1. Assert there are no tick pairs (S10 call, then S1 `preset_change` on the same zone). Under the pre-CPR code this test FAILS. A compare-only fix would also fail it, which is what discriminates the CPR fix from the card's original fix.
- **Test:** `test_s10_dwell_zero_flap_bounded_by_spacing` (CPR D4, ≤ 4 calls / 30 min).
- **Mutation (Reviewer C):** re-insert `and not _compose_away`-style unconditional emit → the storm test fails. Delete the spacing check → the flap test fails.
- **Lint (build-time):** `grep -rn '_last_emitted_range' custom_components/universal_room_automation/` is empty. `grep -n '_compose_away' domain_coordinators/hvac.py` is empty.
- **W1-C P1 interaction:** the P1 S10 golden (A13) and `_last_emitted_range` equality entries are retired or regenerated in the CPR commit, with one line in the build notes naming the change as intended.
- **Live (after operator enable, zone 3 first):**
  - CPR Q4: count per (zone, site, `values_after`) ≤ 3.
  - CPR Q10: S10 pairs < 600 s apart = 0.
  - **Card discriminator:** `ura_activity_log` `climate_write` rows with `site LIKE 'S10%'` per empty zone per hour ≤ 1 in steady state (the old behaviour would have been ~12-48).
  - Zero `preset_change` rows with `manual_class='zero_delta_ura'` within 15 min after an S10 row (CPR Q3).

### D2 — Board hygiene (orchestrator, no code)
- Mark this card `folded_into: HVAC-CUSTOM-PRESET-RANGES-1` and keep status `planned` until CPR ships. Do not count it as an independent build.
- Update its `next` to point here.
- Edit the yaml surgically (memory `feedback_kanban_yaml_surgical_edits_only`).
- Correct the CPR plan's stale anchor `switch.py:2046-2047` → `:2061-2062` the next time that plan is touched.

---

## 8. Knobs

| Number | Rung | Status |
|---|---|---|
| `S10_PRESET_RANGE_MIN_SPACING_S` = 600 | 1 (cloud call-rate bound, reviewed change) | CPR-owned; reused |
| `S10_PRESET_RANGE_MIN_INTERVAL_S` = 7800 | 1 | CPR-owned |
| `S10_COMPOSE_AWAY_MIN_SPACING_S` = 600 | 1 | **fallback only (§6), not created** |
| Kill switch | `switch.ura_hvac_coordinator_guest_mode_actuation` (01 · Custom Preset Ranges) | existing; OFF = no S10 apply |

This plan adds no new knob.

---

## 9. Tier

- **This card standalone: no build (DUPLICATE, folded).**
- **Delivered within CPR (Batch C):** Tier 2-DB + mandatory Reviewer D, per CPR §11. Deploy is held for the operator's explicit go, zone 3 first. CPR merges after W1-C P1.
- The plan-review requirement is satisfied by CPR's two plan reviews. This doc adds only D1's discriminating test and the W1-C golden note, both of which should go to the CPR builder brief.

## 10. Non-goals
- No change to S1, its four gates, the borrow primitive, or the S8/S9/S11/S13 HUMAN_MANUAL raw restores.
- No feed-confirmation oracle (`HVAC-WRITE-CONFIRMATION-ORACLE-1`).
- No standalone code change while the switch stays OFF.
