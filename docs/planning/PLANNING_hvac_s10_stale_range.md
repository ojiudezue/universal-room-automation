# PLANNING — HVAC S10 stale-range re-write after a preset change

**Card:** `HVAC-S10-STALE-RANGE-AFTER-PRESET-CHANGE-1`
**Thread:** hvac
**Status:** pre_planning
**Tier:** **Tier 2** (single-coordinator, single-site, bounded blast radius; S10 is a shared
primitive but the change is additive and gated per-zone — see Non-goals).
**Date:** 2026-10-15
**Branch (intended):** `plan/hvac-s10` on worktree `.claude/worktrees/hvac-s10-plan`.

---

## Institutional context verified

### Code locations surveyed (end-to-end)
- `custom_components/universal_room_automation/domain_coordinators/hvac.py` S10 surface:
  `_async_apply_preset_overrides` (line 4173), `_s10_pass` (4439), `_s10_zone_skip_reason`
  (4364), `_s10_desired` (4409), `_s10_write_one` (4521), `_s10_original_differs` (4738),
  state wiring (750–767), `_zone_last_s1_write` (631, written at ~3929–3933).
- `custom_components/universal_room_automation/domain_coordinators/hvac_strategy.py`
  — `GenericStrategy.set_preset_range` (543), `preset_range_original` (567),
  `preset_range_would_write` (575); `CarrierStrategy._confirmed_on` (654),
  `preset_range_original` (666), `set_preset_range` (692).
- `custom_components/universal_room_automation/domain_coordinators/hvac_const.py` S10
  constants: `S10_PRESET_RANGE_MIN_INTERVAL_S` (1566), `S10_PRESET_RANGE_UNCONFIRMED_LIMIT`
  (1570), `S10_PRESET_RANGE_MIN_SPACING_S` (1575), `S10_PRESET_RANGE_PRESETS` (1584),
  `S10_STATE_SIDE_KEY` (1594). Carrier suppression windows
  `SUPPRESS_TTL_SECONDS_PRESET = 120 s` (`hvac_override.py:304`).

### Design docs read COMPLETELY
- `docs/Coordinator/HVAC_ARCHITECTURE_STATE_OF_PLAY.md` — mandatory. §4.2 (S10 row), §4.3
  (climate_write ledger), §5 (Carrier status vs config feed: status is lagging; 42–79 s
  cloud refresh; 5-min post-write guard on HA's local copy), §9.7 (CPR blockers CLOSED
  by construction), §10 ledger C16/C17/C20/C33 are the directly-relevant corrections.
- `docs/Coordinator/IDENTITY_FUSION_CAMERAS_MANUAL.md` — not applicable (no identity).

### Doc drift discovered while reading (fixed in the same commit as this plan)
Code at file:line wins over the doc. The following were stale and MUST be patched in
`HVAC_ARCHITECTURE_STATE_OF_PLAY.md` (see "Doc corrections required" below):
- §1 line 133 says CPR is DORMANT; card HVAC-CUSTOM-PRESET-RANGES-1 closed `done`
  2026-10-14 and zone_3 has been live since 2026-10-13 (switch ON since 2026-10-02; see
  §3.3 LIVE-STATE NOTE 2026-10-03).
- §8 live-switches table line 372 shows `switch…guest_mode_actuation = off` — stale, now
  on. §8 header date (2026-09-26) is not updated per-row.
- §9 has TWO sections numbered **9.7** (lines 439 and 448). The second (Zone 1 away
  feed-split) must be renumbered **9.9bis** (or **9.A**) — do not re-use 9.7.
- §4.2 S10 row cites the funnel as "HVAC Batch C, built 2026-10-05, not deployed" in
  places; Batch C SHIPPED v5.103.39 (verified in the header snapshot and the card).
  Already fully corrected in some rows; audit remaining "not deployed" wording.

### Prior-art scan (REUSE vs NEW) — proposed additions

| Proposal | Verdict | Where / why |
|---|---|---|
| Per-zone "last S1 preset write" timestamp used to gate S10 | **REUSE** | `HVACCoordinator._zone_last_s1_write[zone_id] = (preset, reason, ts_utc)` at `hvac.py:3929-3933`, declared `hvac.py:631`. Already updated on every APPLIED S1 write. |
| Carrier "post-write guard" window length (120 s) | **REUSE** | `SUPPRESS_TTL_SECONDS_PRESET = 120` (`hvac_override.py:304`). Already covers URA's own echoes; the S10 cooldown should be anchored to the SAME window to avoid introducing a second number. |
| Operator-tunable knob for the cooldown | **NEW — rejected (config-first ruling)** | A Number entity would surface internal Carrier plumbing. Rung 1 module constant per Numbers-Get-Knobs: "fitted-model / API-rate bound — change requires review." |
| New module constant `S10_POST_PRESET_CHANGE_COOLDOWN_S` | **NEW** | Rung 1 in `hvac_const.py`, default = `SUPPRESS_TTL_SECONDS_PRESET` (120 s). Named so a future adjustment is grep-able. |
| New skip-reason `post_preset_change_cooldown` | **NEW** | Returned by `_s10_zone_skip_reason` (extends the existing skip matrix); becomes a new rate-only outcome in `_s10_last_outcome` (`status="skipped"`, `reason="post_preset_change_cooldown"`). |
| Ledger / NM channel | **REUSE** | Debug log via existing `_LOGGER.debug("S10 %s: zone %s skipped (%s)", …)`; no new NM. |

### Prior planning docs consulted
- `docs/planning/PLANNING_hvac_enable_custom_preset_ranges.md` REV 5 (parent CPR plan)
  and its Builder notes — the §3.2 skip matrix (steps 0.5–5) and §6.2 rate/latch model
  are the only moving parts the fix extends.
- `docs/planning/PLANNING_hvac_w1c_p2_ecobee.md` — ecobee adapter is byte-identical on
  the Carrier/Generic path; the fix is Carrier-only in observable effect, but applies
  uniformly across adapters (gate is pre-call, upstream of the strategy).

### Memory bodies pulled
- `project_v5_5_0_inclement_weather_shipped.md`, `project_envoy_boot_incident_2026_06_12.md`
  — unrelated. `feedback_measure_before_build.md`, `feedback_marginal_benefit_pushback.md`,
  `feedback_tier2plus_prior_art_scan.md`, `feedback_config_first_before_code.md` applied
  throughout.

### Config-first ruling
No live knob fixes this. The relevant live knobs — `S10_PRESET_RANGE_MIN_SPACING_S`
(600 s), `S10_PRESET_RANGE_MIN_INTERVAL_S` (7800 s), `SUPPRESS_TTL_SECONDS_PRESET`
(120 s) — are rung-1 module constants. Raising spacing globally over-corrects (every
same-value re-apply would wait a long time). The defect is specifically a *per-zone,
per-preset-change* read-staleness window, not a global rate problem.

---

## Problem (verified from code — producer + consumer check)

**Producer.** `CarrierStrategy.preset_range_original` (`hvac_strategy.py:666-680`) reads
`obs.target_low` / `obs.target_high` off the climate entity. Per §5 of the state-of-play,
`preset_mode` is the **status feed** (lagging; 42–79 s cloud refresh) and the setpoints
URA displays come from the activity the status feed names (`climate.py:230-240` of
`ha_carrier`). After S1 pins a new preset (via `emit_set_preset_mode` → `set_config_hold`),
the status feed's `preset_mode` + its `target_temp_{low,high}` can lag the config feed's
`hold_activity` for up to the Carrier 5-min post-write guard window (C21) — during which
the HA attributes show the **previous** preset's range even though `hold_activity` and
`preset_mode` both already name the new preset.

**Consumer.** `_s10_write_one` step 9 (`hvac.py:4536-4544`) captures the HA view as the
"original" when no snapshot exists for this `(zone, preset)` yet. The confirmation gate
`CarrierStrategy._confirmed_on` (`hvac_strategy.py:654-664`) requires both
`preset_mode == preset` AND `hold_activity == preset`; it does NOT measure the staleness
of the setpoint legs themselves. Within the Carrier post-write guard window, both feeds
can already name the new preset while the setpoint legs still reflect the OLD preset.

**Effect.** On the first full tick after a preset change (next 5-min tick, since S1
also sets `_zones_written_this_cycle` which S10 skip-matrix step 3 honours), S10's
P4 compare (`set_preset_range` lines 724–729) does not match (HA shows old preset legs,
not desired), so it emits `set_activity_setpoint`. The write LANDS correctly against the
new preset's profile; the following tick re-reads the (now fresh) HA view and
`SKIPPED_ALREADY_CORRECT` fires. Net: **one redundant wire call per preset change per
zone, per preset first visited after the change** — the parent card's observation.

**Harm.** Measured small (parent card: "no comfort or cost impact observed; the range
held"). Grows with CPR rollout (zones 1 + 2) and with preset-change frequency (fast-path
entry/exit, pre-arrival, house-state transitions). Doubles as a false drift signal in
`climate_write` analytics.

---

## Falsifiable invariant (what the fix guarantees)

> **INV-S10-COOLDOWN:** For any zone `Z` whose `_zone_last_s1_write[Z].ts` is within
> `S10_POST_PRESET_CHANGE_COOLDOWN_S` of the current cycle time, S10 writes **zero**
> wire calls against `Z` (apply or restore) on that tick. The next S10 wire opportunity
> is the first full tick ≥ cooldown-expiry.

Falsifier (any reachable path): a `set_activity_setpoint` service call originating from
S10 (`site ∈ {S10_preset_range, S10_preset_range_restore}`) whose
`ts_issued − _zone_last_s1_write[Z].ts < S10_POST_PRESET_CHANGE_COOLDOWN_S`.

---

## Deliverables

### D1 — Per-zone post-preset-change S10 cooldown

**Change (one site; additive):** extend `_s10_zone_skip_reason` (`hvac.py:4364`) with
a NEW first-check (after step 0.5 climate_unreadable) that returns
`"post_preset_change_cooldown"` when `_zone_last_s1_write[zone_id]` exists and
`(now - rec[2]).total_seconds() < S10_POST_PRESET_CHANGE_COOLDOWN_S`. Fail-closed on
exception (treat as cooldown). The pre-call re-check in `_s10_write_one` already
re-runs the full skip matrix (`hvac.py:4664`), so the gate also catches a cooldown
that armed during the write-ahead save await.

**New constant** `hvac_const.py`:
```python
# S10 defers for one Carrier post-write guard window after S1 pins a preset,
# so a stale status-feed read of target_low/target_high (C21) cannot drive a
# redundant preset_range write. Rung 1 — tracks SUPPRESS_TTL_SECONDS_PRESET.
S10_POST_PRESET_CHANGE_COOLDOWN_S: Final = SUPPRESS_TTL_SECONDS_PRESET  # 120 s
```
(Import `SUPPRESS_TTL_SECONDS_PRESET` or inline-document the 120 s value; prefer
re-using the Carrier window so a future tuning touches one site.)

**No new knob, no new NM, no new persisted state.** The cooldown is RAM-only, re-armed
on every APPLIED S1 write (which already stamps `_zone_last_s1_write`); boot and reload
start with an empty map, which is the correct behaviour (no cooldown needed until S1
writes).

### Non-goals (explicit)
- No change to adapter verbs (`set_preset_range`, `preset_range_original`).
- No change to `_zone_last_s1_write` shape or write site.
- No change to the ecobee adapter.
- No persistence change (snapshots, records untouched).
- No restore-pass semantics change beyond the cooldown gate (restore still runs after
  cooldown expires; a zone whose S1 preset flips does not race its own restore).

---

## Acceptance criteria

- **Verify (unit):** `_s10_zone_skip_reason(zone_id, zone)` returns
  `"post_preset_change_cooldown"` iff `now − _zone_last_s1_write[zone_id].ts <
  S10_POST_PRESET_CHANGE_COOLDOWN_S` and no earlier skip-matrix step fires.
- **Verify (unit):** with cooldown active, `_s10_pass(mode="apply")` and
  `_s10_pass(mode="restore")` emit zero calls into `strategy.set_preset_range` and
  zero `climate_write` rows for the affected zone.
- **Test:** new tests in `quality/tests/hvac/test_s10_post_preset_change_cooldown.py`:
  (a) cooldown active → skip; (b) cooldown expired → write proceeds; (c) pre-call
  re-check catches an await-arrival cooldown; (d) only the written zone is gated
  (sibling zones unaffected); (e) boot with no `_zone_last_s1_write` entry does not
  skip.
- **Sensor:** `get_s10_diagnostics()` outcome map carries
  `{status: "skipped", reason: "post_preset_change_cooldown"}` for the skipped tick.
- **Ledger:** no `s10_possible_wrong_profile` rows attributable to a preset-change
  stale read (should drop to ~zero on zone 3 after deploy — baseline it below).
- **Live:** on `develop` restart, within one full S1 cycle the first preset change on
  zone_3 (CPR rollout) does NOT produce an immediate `climate_write` with
  `site="S10_preset_range"` on the same tick as the S1 `preset_change` row. Expect the
  S10 write (if still needed) on the NEXT full tick (≥ 300 s + up to 120 s cooldown
  deferral).
- **Live baseline (measure-before-build):** probe recorder DB on `develop` prior to
  ship: `SELECT zone, COUNT(*) FROM ura_activity_log WHERE action='climate_write' AND
  json_extract(details_json,'$.site') IN ('S10_preset_range','S10_preset_range_restore')
  AND timestamp > datetime('now','-7 days') GROUP BY zone;` and the correlated count
  of `preset_change` rows per zone in the same window. Record both pre- and post-deploy;
  the ratio (S10 writes) / (S1 preset_changes) should drop meaningfully on zone_3 after
  ship.

---

## Review tier + framings

**Tier 2** (two framing-disjoint reviews before build dispatch; one plan review per
Plan-Review protocol).

- **Review A (correctness + edge cases):** the cooldown predicate; interaction with the
  existing skip matrix order; the pre-call re-check; ecobee no-op path; latch/record
  state preserved across a cooldown skip; D-LOW-2 generation guard still correct.
- **Review B (cross-coordinator + lifecycle):** boot/reload with empty
  `_zone_last_s1_write`; a cooldown that arms mid-await; a user toggle of switch 01
  during cooldown; a fast-path S1 write that updates `_zone_last_s1_write`;
  interaction with the arrester's own preset suppression (`SUPPRESS_TTL_SECONDS_PRESET`,
  same window on the *climate entity* side).

Tier 2 (not 2-DB): no DAO change, no payload-shape change, no shared-primitive change
beyond extending S10's own skip matrix. If the reviewer or operator judges the ripple
higher (e.g. ecobee S10 interactions once live), elevate to 2-DB per standing policy.

---

## Doc corrections required (apply in same commit as the plan)

In `docs/Coordinator/HVAC_ARCHITECTURE_STATE_OF_PLAY.md`:

1. **Line 133-134 (§1 summary).** Replace
   > "the **setpoint** layer (D9 compose-away / Custom Preset Ranges) is DORMANT (`switch.ura_hvac_coordinator_guest_mode_actuation` = off)."

   with
   > "the **setpoint** layer (Custom Preset Ranges, formerly D9 compose-away) is **LIVE on zone_3 since 2026-10-13** via `hvac_s10_rollout_zone_ids`; `switch.ura_hvac_coordinator_guest_mode_actuation` ON since 2026-10-02 21:28:45Z; parent card HVAC-CUSTOM-PRESET-RANGES-1 closed done 2026-10-14."

2. **Line 372 (§8 live-switches table).** Replace
   > `| switch.ura_hvac_coordinator_guest_mode_actuation (D9 / Custom Preset Ranges) | **off** |`

   with
   > `| switch.ura_hvac_coordinator_guest_mode_actuation (Custom Preset Ranges) | **on** since 2026-10-02 21:28:45Z (§3.3 LIVE-STATE NOTE); zone_3 in hvac_s10_rollout_zone_ids since 2026-10-13 |`

   Add a one-line note above the table: *"Values dated 2026-09-26 unless the row says otherwise."*

3. **Line 448 (§9 defect list).** Renumber the duplicate `**9.7`** heading
   (Zone 1 away feed-split) to **`9.9`** or **`9.A`** — section numbers must be unique.
   Update any back-reference ("§9.7") in `HVAC-ZONE1-MANUAL-OSCILLATION-1` card to
   point at the new number.

4. **§10 corrections ledger.** Append:

   > **C37 (2026-10-15, HVAC-S10-STALE-RANGE-AFTER-PRESET-CHANGE-1) — WRONG: "D9 / Custom Preset Ranges is DORMANT (switch off)" (§1 line 133; §8 switch row).** Switch flipped ON 2026-10-02 21:28:45Z (entity re-create, not restart); zone_3 added to `hvac_s10_rollout_zone_ids` 2026-10-13 and held through live validation; parent card closed 2026-10-14. §3.3 LIVE-STATE NOTE 2026-10-03 was the earliest in-doc note; §1 and §8 were not updated. Residual: a stale status-feed read within the Carrier post-write guard window causes one redundant `set_activity_setpoint` per preset change per zone (plan `docs/planning/PLANNING_hvac_s10_stale_range.md`).

5. **§4.2 S10 row** (line 223). Add at the end of the row:
   > "Known residual (2026-10-15): a preset change can cause one redundant S10 write on the first full tick after it, because `preset_range_original` reads the status-feed setpoints which lag within the Carrier 5-min post-write guard (C21). Gated by a per-zone `S10_POST_PRESET_CHANGE_COOLDOWN_S` in the plan above."

(These are 4 one-line surgical edits plus one ledger paragraph; no structural rewrite.)

---

## Open questions

- **Q1 — ecobee interaction.** The ecobee adapter stores URA-side ranges and never
  reads back a stale cloud leg (the W1-C P2 build note says `effective_range` is the
  oracle). The cooldown should be a no-op for ecobee zones, but the gate is applied in
  `_s10_zone_skip_reason` upstream of the adapter — confirm no harm (ecobee just
  skips harmlessly during cooldown). Not expected to need an adapter branch.
- **Q2 — AC-reset preset write.** `_restore_after_reset` writes a preset through the
  arrester, not through S1; `_zone_last_s1_write` is updated only by S1 APPLIED writes.
  An AC-reset preset flip followed by a stale S10 read is theoretically possible, but
  no evidence has been seen. Scope-out for this cycle; revisit if the probe shows it.
- **Q3 — Cooldown length.** Default 120 s mirrors `SUPPRESS_TTL_SECONDS_PRESET`.
  Carrier observed status refresh is 42–79 s; 120 s covers the long tail. If the
  recorder probe shows stale-reads > 120 s, raise to the Carrier full-poll bound
  (300 s). Measure first.

---

## Build sequence (for the builder, not this cycle)

1. Add `S10_POST_PRESET_CHANGE_COOLDOWN_S` to `hvac_const.py`.
2. Extend `_s10_zone_skip_reason` with the cooldown check (first after
   `climate_unreadable`); the pre-call re-check inherits automatically.
3. Add unit tests.
4. Run `.venv-ha/bin/python -m pytest quality/tests/hvac/ -k "s10 or preset_range" -v`.
5. Live-validate on zone_3; probe the ratio before and after.

---

## Report (for the parent orchestrator)

- **S10 defect:** CONFIRMED from code. Mechanism = `CarrierStrategy.preset_range_original`
  reads the lagging status-feed setpoints (`hvac_strategy.py:666-680`); within the
  Carrier 5-min post-write guard (C21 of §10), both `preset_mode` and `hold_activity`
  can already name the new preset while the setpoint legs still reflect the previous
  profile. `_s10_write_one` step 9 captures the stale read as "original" and the P4
  compare writes once; next tick is `SKIPPED_ALREADY_CORRECT`. Harm = 1 redundant wire
  call per preset change per zone per preset first visited after the change.
- **REUSE:** `_zone_last_s1_write` already carries the per-zone APPLIED S1 preset-write
  timestamp (`hvac.py:631`, updated at `hvac.py:3929-3933`). No new state needed.
- **Config-first:** no live knob fixes it. The only existing per-zone post-write
  defence is Carrier's own 120 s suppression on the climate entity, which S10 does not
  consult. The fix is a one-line gate using existing state + one rung-1 constant.
- **Tier:** 2 (not 2-DB) — single site, additive, no DAO or payload change.
- **Verdict:** proceed to plan review (ONE adversarial pass per Tier-2 protocol),
  then build. Not urgent (parent card: low value until CPR rolls out to zones 1 + 2).
