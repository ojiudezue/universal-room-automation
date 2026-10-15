# PLANNING — HVAC S10 stale-range re-write after a preset change

**Card:** `HVAC-S10-STALE-RANGE-AFTER-PRESET-CHANGE-1`
**Thread:** hvac
**Status:** pre_planning
**Rev:** **2** (2026-10-15) — fully revises Rev 1 against plan review
`docs/reviews/code-review/plan_hvac_s10_review.md` (F1-F8 FIX-REQUIRED) and against
the 2026-10-15 read-only recorder probe (below). Rev 1 shape (SUPPRESS_TTL_SECONDS_PRESET
cooldown anchored on `_zone_last_s1_write` only) is **withdrawn** — it duplicates the
existing same-tick gate at `hvac.py:2259` / `:4393` / `:4664` and is too short to cover
the observed staleness window.
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

**What the probe refutes.**

- **Rev 1's mechanism "stale status-feed read; write lands correctly".** The failure
  was a local raise in 0.3 ms, not a landed write. (**F3**.) `carrier_api/climate.py:
  222-230` reads `_current_activity()` (the CONFIG activity named by status); it falls
  back to `_status_zone` (stale status setpoints) only when `_current_activity()`
  returns None. `_current_activity()` returns None when `current_status_activity()`
  returns None (`carrier_api/config.py:197-218`: no matching config entry, or an
  `api_id` mismatch between status and config), and
  `async_set_activity_setpoint` raises `HomeAssistantError("Current activity
  unavailable")` at `climate.py:551-553` under the same condition.
- **The 120 s cooldown.** The actual stale window was **~422 s**. 120 s ends at the
  next S10 tick (300 s) which is exactly when the failure occurred. Rev 1 would NOT
  have prevented this write. (**F2**.) The existing cycle-entry seed at `hvac.py:2259`
  already enforces a 120 s gate on `_zone_last_s1_write`; Rev 1 was a duplicate.
  (**F1**.)

**What the probe does NOT establish (uncertainty called out, per `No Fabrication`).**
Mechanism is **PARTIAL / UNVERIFIED (n=1)**. A single HomeAssistantError without the
error text recorded is consistent with "unresolvable activity" (the plausible
mechanism), but also with any other local raise under
`async_set_activity_setpoint`. The acceptance tests below are written to
*discriminate* between "stale legs, landed write" and "unresolvable activity,
rejected write" (per F6 / `feedback_falsify_before_asserting.md`).

---

## Review resolution table

Each finding in `docs/reviews/code-review/plan_hvac_s10_review.md` and this Rev 2's response.

| # | Finding (short) | How Rev 2 resolves it |
|---|---|---|
| F1 | D1 duplicates existing same-tick gate (`hvac.py:2259` seed + `:4393` + `:4664`). Prior-art table missed consumers at `:2259` and `:5594`. | Rev 1 gate withdrawn. New gate anchors on OBSERVED preset-change timestamp (not `_zone_last_s1_write`), with a settle window **longer** than the 120 s already enforced by the cycle seed. Prior-art table rewritten (§Prior-art) to list every `_zone_last_s1_write` consumer: `:2259` (cycle seed), `:3929-3933` (writer), `:5304` (docstring), `:5594` (away-edge key). |
| F2 | 120 s cannot cover the measured 422 s staleness; the write landed on the next 300 s tick. | Window is now sized from the measurement (§Measurement), default **`S10_POST_PRESET_CHANGE_SETTLE_S = 600 s`** — covers the observed 422 s + a full ~1 tick of jitter / cloud lag. Named as its OWN constant, not coupled to `SUPPRESS_TTL_SECONDS_PRESET` (F7). "Effect" paragraph rewritten so it no longer contradicts itself. |
| F3 | Mechanism contradicts `ha_carrier` source + the evidence (local raise under 1 ms, not a landed write). | Mechanism re-stated as PARTIAL: during the Carrier post-write transition `current_status_activity()` can return None → both legs fall back to stale `_status_zone` AND `async_set_activity_setpoint` locally raises (`climate.py:551-553`). Marked **UNVERIFIED (n=1)** throughout. Acceptance tests discriminate "stale legs" from "unresolvable activity" (§Acceptance). §4.2 state-of-play residual note is edited to mark the mechanism UNVERIFIED. |
| F4 | Harm understated: failure-counter latch (3 strikes → `call_failed` + NM, S10 stops managing away) AND snapshot poisoning on zones 1/2 rollout. | Both named explicitly in §Harm. Both covered by D1 **and D2** (D2 is the correctness fix for the latch itself, operator shape (a)). Acceptance criterion added for each harm. |
| F5 | Anchor is S1-only; other writers (S4 arrester, S7 restore, AC-reset `_restore_after_reset`, egress resume, excursion `_auto_return`, S11/S13, human, Bryant schedule) all change the preset without stamping `_zone_last_s1_write`. | Anchor is now the OBSERVED `preset_mode` / `hold_activity` transition on the climate state, maintained in `hvac_zones.update_zone_climate_state` (RAM-only `_zone_last_observed_preset_change[zone_id]`). Any writer that changes the preset — URA or external — arms the settle window. D2 (shape (a)) is the orthogonal safety net for any residual local-raise path the window misses. |
| F6 | Invariant already holds (hollow, Bug Class #62); acceptance tests would pass against a no-op. | Invariant restated over the OBSERVED-transition window AND the latch counter AND the snapshot capture (not the "same-tick" window the existing seed already covers). Each acceptance test is written to FAIL on today's `develop` — see §Acceptance "Discriminating assertions". |
| F7 | Rung-1 OK, but `S10_POST_PRESET_CHANGE_COOLDOWN_S = SUPPRESS_TTL_SECONDS_PRESET` couples two concepts (Bug Class #63). | **New constant** `S10_POST_PRESET_CHANGE_SETTLE_S` is its own named rung-1 value (default 600 s), NOT aliased to `SUPPRESS_TTL_SECONDS_PRESET`. Separate semantic: "Carrier read-staleness window after an observed preset transition" vs. arrester echo-suppression. |
| F8 | Baseline SQL groups by `zone` but `zone_id` lives in `details_json`; §3.3 / §4.1 of state-of-play still carry stale "not deployed" wording; code comments `~3938` / `~5593` still reference `§9.7` (now §9.9). | Baseline SQL rewritten in §Acceptance (`json_extract(details_json,'$.zone_id')`). §Doc corrections includes: audit of the 5 "not deployed" rows (shipped versions filled per commit `1480811ba`), the §9.7→§9.9 comment fix in `hvac.py` ~3938 and ~5593, and marking the §4.2 S10-row residual mechanism UNVERIFIED. |

The 2026-10-15 state-of-play commit `1480811ba` already filled 5 stale "not deployed" labels with ship versions and marked the S10 residual mechanism unverified. §Doc corrections below is now limited to the two remaining stale `§9.7` code comments.

---

## Falsifiable invariant (what Rev 2 guarantees)

> **INV-S10-SETTLE:** For any zone `Z` whose OBSERVED preset
> (`preset_mode` or `hold_activity`) transitioned within
> `S10_POST_PRESET_CHANGE_SETTLE_S` of the current cycle time, S10 performs
> **zero** of each of: (i) a `strategy.set_preset_range` emission (`site ∈
> {S10_preset_range, S10_preset_range_restore}`); (ii) a `_s10_snapshots[Z][preset]`
> capture; (iii) an increment of `_s10_records[Z][preset|mode].failures`. The next
> S10 wire opportunity is the first full tick ≥ (observed-transition-ts + settle).

> **INV-S10-LATCH-RESET:** For any (Z, preset, mode), a `WriteStatus.APPLIED` or
> `WriteStatus.SKIPPED_ALREADY_CORRECT` on the record ALSO resets
> `rec["failures"] = 0`, so a rare transient local-raise (e.g. unresolvable
> activity during a Carrier transition) can never accumulate across preset
> segments to the `S10_PRESET_RANGE_UNCONFIRMED_LIMIT` latch.

Falsifiers (any reachable path):
1. A `set_activity_setpoint` call at site `S10_*` for Z whose
   `ts_issued − _zone_last_observed_preset_change[Z].ts <
   S10_POST_PRESET_CHANGE_SETTLE_S`.
2. A snapshot capture at `hvac.py:4541-4544` for (Z, preset) under the same window.
3. A failure increment at `hvac.py:4714` under the same window.
4. A record with `failures > 0` after `_s10_success` ran.

---

## Chosen fix shape — operator shape **(a) + (b)**, with (b) using an OBSERVED anchor

**Marginal-benefit decomposition** (`feedback_marginal_benefit_pushback.md`):

- **Simplest-only (a) — reset failures on success.** Benefit: closes the slow march
  to the 3-strike `call_failed` latch on zone_3 (today's observable harm). Risk:
  trivial (one write-site, same scope). Does **not** address snapshot poisoning
  for zones 1 + 2 rollout — the first visit to a preset *during* the staleness
  window can still persist a wrong "original" into
  `_s10_snapshots[Z][preset]` (`hvac.py:4541`), and that snapshot is **never
  overwritten** on later visits (step 9 captures only if the key is absent).
  Later restore (switch OFF, or ruling A6 removal) would write the wrong range
  into the device profile. Insufficient on its own.
- **Simplest-only (b) — observed-transition settle gate.** Benefit: prevents the
  stale read AND the snapshot capture AND (because no wire call fires) the
  failure increment. Covers ALL writers via the OBSERVED anchor, not just S1
  (F5). Risk: one new RAM-only observer in `hvac_zones.update_zone_climate_state`
  — small, well-contained, uses the already-read `preset_mode`/`hold_activity`
  values. Does **not** address the rare path where a local raise still happens
  AFTER the window expires (e.g. a longer-than-measured transition, or an
  unrelated transient during a periodic tick) — a single such raise is harmless,
  but three in a row across preset segments still latches because failures never
  clear.
- **(a) + (b) together.** Benefit: both the slow latch creep AND the stale read
  AND the snapshot poisoning risk are closed. The marginal cost of adding (a) on
  top of (b) is ONE additional assignment in `_s10_success` (`rec["failures"] =
  0` next to the existing `rec["writes"] = 0`). The marginal cost of adding (b)
  on top of (a) is one observer + one constant + one skip-matrix step. Both are
  additive, Rung-1, no new signal, no new NM, no new persisted state. **Chosen:
  (a) + (b).** The two-piece defence buys the invariant pair above with no
  measurable ingredient-risk escalation.

### Why (b)'s anchor is OBSERVED, not S1 (resolving F5)

The failure site is the Carrier post-transition read-staleness window. It opens
on *any* preset-change wire call that completes against the thermostat —
URA-originated (S1, S4 arrester revert, S7 restore, excursion `_auto_return`,
AC-reset `_restore_after_reset`, egress resume, S11/S13), or external (human in
the app, wall-mounted change, Bryant schedule — zones 2/3 still run schedules
per state-of-play §5). Anchoring on `_zone_last_s1_write` would silently exclude
every non-S1 writer; the observer approach keys off the fact itself.

The observer is a one-liner in `hvac_zones.update_zone_climate_state` (the
existing per-tick zone-climate-state refresh): when the newly-read
`preset_mode` or `hold_activity` differs from the previous RAM copy, stamp
`self._zone_last_observed_preset_change[zone_id] = (prev, new, utcnow())`.
The map lives on the coordinator (next to `_zone_last_s1_write`). Reload /
boot: empty map (correct — no settle needed until a transition is observed).

### Why **600 s**, not 120 s and not 300 s (resolving F2/Q3)

- Observed staleness in the one measured incident: **422 s**.
- A single full periodic tick is 300 s; the first observable "retry would run"
  tick after a preset change can land at 300 s + jitter, so a window shorter
  than 300 s is useless by construction.
- `SUPPRESS_TTL_SECONDS_PRESET` (120 s) is unrelated semantics (arrester echo
  suppression on OUR writes against the climate entity). Coupling them was
  Rev 1's F7 error.
- 600 s = 422 s observed + a ~180 s margin to cover the next tick's jitter and
  Carrier's own 42-79 s status-refresh variance observed in §5 of the
  state-of-play. If future measurements show the stale window reaching 500+ s
  routinely, raise to 900 s; if it never exceeds 300 s across a representative
  sample post-ship, drop to 450 s. The constant is the knob.
- Numbers-get-knobs: Rung 1 (module constant), per
  `feedback_marginal_benefit_pushback.md` — this governs a Carrier API-rate /
  read-staleness bound, not a user policy. Operator tuning requires a code
  review by design.

---

## Institutional context verified (Rev 2)

### Code locations surveyed (end-to-end)

- `custom_components/universal_room_automation/domain_coordinators/hvac.py`
  - S10 surface (unchanged from Rev 1): `_async_apply_preset_overrides`
    (`:4173`), `_s10_pass` (`:4439`), `_s10_zone_skip_reason` (`:4364`),
    `_s10_desired` (`:4409`), `_s10_write_one` (`:4521`),
    `_s10_original_differs` (`:4738`), state wiring (`:750-767`).
  - `_zone_last_s1_write` surface: declared `:631`; writer `:3929-3933`; cycle
    seed consumer `:2258-2261` (**ADDED** per F1); away-edge consumer `:5594`
    (**ADDED** per F1).
  - **Observer-site target:** `hvac_zones.py`
    `ZoneManager.update_zone_climate_state` is where `preset_mode` /
    `hold_activity` are refreshed each tick; the per-zone RAM dict the gate
    reads is written adjacent to that refresh.
  - **§9.7 → §9.9 stale comment references in code:** `hvac.py` ~3938 and
    ~5593 (both say "§9.7" in a docstring/comment; §9.7 is now the CPR
    blockers section and §9.9 is the Zone 1 away feed-split).
- `custom_components/universal_room_automation/domain_coordinators/hvac_strategy.py`
  — `GenericStrategy.set_preset_range` (`:543`); `CarrierStrategy._confirmed_on`
  (`:654`); `preset_range_original` (`:666`); `set_preset_range` (`:692`).
- `custom_components/universal_room_automation/domain_coordinators/hvac_const.py`
  — S10 constants `:1566`-`:1594`.
- **Upstream (ha_carrier) referenced for mechanism only, not modified:**
  `carrier_api/climate.py:222-240` (setpoint source `_current_activity()`
  → `_status_zone` fallback); `climate.py:551-553` ("Current activity
  unavailable" local raise); `carrier_api/config.py:197-218`
  (`current_status_activity` returns None on status-type / `api_id`
  mismatch).

### Design docs read COMPLETELY

- `docs/Coordinator/HVAC_ARCHITECTURE_STATE_OF_PLAY.md` — mandatory, re-read
  after commit `1480811ba`. §4.2 S10 row carries the Rev 2 residual with the
  UNVERIFIED mechanism marker; §5 Carrier status-vs-config feed is the
  mechanism anchor; §10 corrections ledger C37 is the Rev 1 → Rev 2 record.
- `docs/Coordinator/IDENTITY_FUSION_CAMERAS_MANUAL.md` — not applicable (no
  identity surface).

### Prior-art scan (REUSE vs NEW) — Rev 2 additions

| Proposal | Verdict | Where / why |
|---|---|---|
| Per-zone **observed-preset-change** timestamp | **NEW (minimal)** | No existing map keys off `preset_mode` / `hold_activity` transitions. `_zone_last_s1_write` (`hvac.py:631`, writer `:3929-3933`, consumers `:2258-2261`, `:5304`, `:5594`) is S1-only and would miss every non-S1 writer (F5). The new map is RAM-only, written in `hvac_zones.update_zone_climate_state` next to the existing per-tick refresh. |
| Settle window constant `S10_POST_PRESET_CHANGE_SETTLE_S` | **NEW** | Rung 1 in `hvac_const.py`, default **600 s**, NOT aliased to `SUPPRESS_TTL_SECONDS_PRESET` (F7). Named so a future tuning is grep-able. |
| Skip-matrix step `post_preset_change_settle` | **NEW** | Returned by `_s10_zone_skip_reason` (first check after step 0.5 `climate_unreadable`, BEFORE step 3 `s1_same_tick` — so the OBSERVED gate strictly dominates the shorter S1-only gate). New `_s10_last_outcome` row with `status="skipped"`, `reason="post_preset_change_settle"`. |
| Reset `rec["failures"] = 0` on `_s10_success` | **NEW (shape (a))** | `_s10_success` (`hvac.py:4766-4779`) currently resets only `writes`. One additional line. |
| Snapshot-capture gate under settle | **REUSE (D1 covers it)** | The new skip-matrix step short-circuits `_s10_pass` for the whole tick, so step 9 (`:4536-4544`) is unreachable while settle is armed. No separate gate needed. |
| Operator-tunable knob | **NEW — rejected** | Carrier read-staleness bound; change requires review per Numbers-Get-Knobs. |
| Ledger / NM channel | **REUSE** | Debug via existing `_LOGGER.debug("S10 %s: zone %s skipped (%s)", …)`; no new NM. |

### Prior planning docs consulted

- `docs/planning/PLANNING_hvac_enable_custom_preset_ranges.md` REV 5 (parent CPR
  plan): §3.2 skip matrix (steps 0.5-5) and §6.2 rate/latch model are the
  moving parts Rev 2 extends.
- `docs/planning/PLANNING_hvac_w1c_p2_ecobee.md`: the ecobee adapter stores
  URA-side ranges (`effective_range` is the oracle); the Rev 2 gate is a
  no-op harmless skip for ecobee zones. No adapter branch required.

### Memory bodies pulled

- `feedback_measure_before_build.md` — gated this entire Rev 2.
- `feedback_marginal_benefit_pushback.md` — (a) vs (b) vs (a)+(b) decomposition.
- `feedback_tier2plus_prior_art_scan.md`, `feedback_config_first_before_code.md`,
  `feedback_falsify_before_asserting.md`, `feedback_hollow_test_anchors.md`,
  `feedback_coincidental_equality_masks_concept_split.md` (F7) all applied.
- `project_v5_5_0_inclement_weather_shipped.md`,
  `project_envoy_boot_incident_2026_06_12.md` — unrelated, consulted for completeness.

### Config-first ruling (unchanged)

No live knob fixes this. The relevant tunables (`S10_PRESET_RANGE_MIN_SPACING_S`
= 600 s, `S10_PRESET_RANGE_MIN_INTERVAL_S` = 7800 s, `SUPPRESS_TTL_SECONDS_PRESET`
= 120 s) are rung-1 constants and address a different concern (rate / latch /
echo). The defect is a per-zone, per-observed-preset-change read-staleness
window, which no existing knob gates.

---

## Problem (verified from code + 2026-10-15 probe — PARTIAL mechanism, n=1)

**Producer.** `CarrierStrategy.preset_range_original` (`hvac_strategy.py:666-680`)
reads `obs.target_low` / `obs.target_high` off the climate entity. Per §5 of the
state-of-play, HA's `target_temp_{low,high}` come from `_current_activity()`
(`ha_carrier/climate.py:222-230`), the CONFIG activity named by the status feed;
when `_current_activity()` returns None, HA falls back to `_status_zone` (the
stale status setpoints). `async_set_activity_setpoint` (`ha_carrier/climate.py:
551-553`) raises `HomeAssistantError("Current activity unavailable")` under the
same None condition. `current_status_activity()` (`carrier_api/config.py:
197-218`) returns None when the status activity type has no matching config
entry or when `api_id` mismatches between status and config.

**Consumer.** `_s10_write_one` (`hvac.py:4521`) calls
`strategy.preset_range_original` at step 9 (`:4537`) to capture a snapshot, and
again just before the wire call (`:4637`) as a no-await re-check. Both reads
pass through `_current_activity()`. The `_confirmed_on` gate
(`hvac_strategy.py:654-664`) requires both `preset_mode == preset` AND
`hold_activity == preset`; it does NOT measure setpoint-leg freshness.

**Effect (revised per probe).** On the first *full periodic* tick after a
preset change (300 s + jitter), S10 reaches `_s10_write_one`. If the Carrier
post-transition window has not closed, two reachable outcomes:

1. **Stale legs + landed write** (NOT observed in the probe — hypothesised, not
   demonstrated). `_current_activity()` returns the CONFIG activity whose
   setpoints match the new preset, but HA's cache for `target_temp_{low,high}`
   has not refreshed on the ATTRIBUTE side yet. P4 compare mismatches, S10
   emits, write LANDS. Mechanism UNVERIFIED.
2. **Unresolvable activity + rejected write** (observed on 2026-10-14; n=1).
   `current_status_activity()` returns None → `_current_activity()` is None →
   HA attribute setpoints fall back to the stale `_status_zone` values AND
   `async_set_activity_setpoint` locally raises
   `HomeAssistantError("Current activity unavailable")` in ~0.3 ms. S10 records
   a FAILED/`emit_raised` → `rec["failures"] += 1`. The next successful
   APPLIED on the same (zone, preset, mode) resets `writes` but NOT
   `failures` (`hvac.py:4766-4779`), so the counter persists until the value
   changes.

**Harm (expanded per F4).**

1. **Failure-counter latch.** `_s10_success` resets `writes` only. Three
   consecutive transient local-raises *across preset segments* (not within one)
   accumulate to `S10_PRESET_RANGE_UNCONFIRMED_LIMIT = 3` and trigger a
   `call_failed` latch + NM; S10 stops managing that (zone, preset) until the
   value changes or operator intervention. Live store at probe time:
   `zone_3 away|apply failures: 1`. 2 more rare transients + no value change
   latches it.
2. **Snapshot poisoning.** `_s10_write_one` step 9 (`hvac.py:4536-4544`)
   captures the "original" range only once per (zone, preset) and never
   overwrites it. If the *first-ever* visit to a (zone, preset) happens while
   the legs are stale, the PREVIOUS preset's range is persisted as that
   preset's device original. Later restore (switch OFF or ruling A6 rollout
   removal) then writes the wrong range into the Carrier profile. Zone_3
   snapshots are correct (dated 2026-10-13, pre-stale-event). This harm is
   reachable on **zones 1 + 2 at CPR rollout** — exactly when the fix matters.
3. **False drift signal.** Every FAILED/`emit_raised` row is a
   `climate_write` anomaly carrying `wire_ok=false` in `details_json`;
   dashboards and anomaly detectors see this as adapter drift.

Base-rate: **1 / 544** zone_3 preset segments since 2026-10-01 exhibited this
pattern. Rare, but a 3-strike cumulative latch does not need frequency — it
needs persistence.

---

## Deliverables

### D1 — Per-zone post-observed-preset-change S10 settle (shape (b))

**Change 1 (observer, new RAM map).** In
`hvac_zones.ZoneManager.update_zone_climate_state`, when the newly-read
`preset_mode` or `hold_activity` differs from the previous RAM copy, call the
coordinator with the transition: `coordinator._note_observed_preset_change(
zone_id, prev_preset, new_preset, utcnow())`. The coordinator-side method
writes `self._zone_last_observed_preset_change[zone_id] = (prev, new, ts)`.
RAM-only; boot/reload = empty (correct; no settle until a transition is
observed).

**Change 2 (skip-matrix step, additive).** Extend `_s10_zone_skip_reason`
(`hvac.py:4364`) with a NEW check inserted **after step 0.5
`climate_unreadable` and BEFORE step 3 `s1_same_tick`**: return
`"post_preset_change_settle"` when
`_zone_last_observed_preset_change.get(zone_id)` exists AND `(now - ts) <
S10_POST_PRESET_CHANGE_SETTLE_S`. Fail-closed on exception (treat as settle).
The pre-call re-check at `_s10_write_one:4664` already re-runs the full skip
matrix, so the gate also catches a settle that armed during the write-ahead
save await.

**New constant** `hvac_const.py`:

```python
# S10 defers for one Carrier post-write staleness window after any
# OBSERVED preset transition on the zone (any writer: S1, arrester,
# S7 restore, AC-reset, egress, excursion, S11/S13, human, Bryant
# schedule). Prevents a stale status-feed read of target_low/high
# AND the matching unresolvable-activity local raise from driving a
# redundant or doomed set_preset_range AND from poisoning a first-visit
# snapshot. NOT the same semantic as SUPPRESS_TTL_SECONDS_PRESET
# (arrester echo on URA's own writes); do not couple them. Rung 1 —
# measured against the 2026-10-14 incident (422 s stale window).
S10_POST_PRESET_CHANGE_SETTLE_S: Final = 600  # seconds
```

**No new knob, no new NM, no new persisted state.**

### D2 — Reset `rec["failures"] = 0` on `_s10_success` (shape (a))

**Change.** In `_s10_success` (`hvac.py:4766`), add `rec["failures"] = 0`
next to the existing `rec["writes"] = 0`. A legitimate successful outcome
(APPLIED on current value, or SKIPPED_ALREADY_CORRECT, or a confirming view
at the limit) discharges the whole retry budget, not just the writes
counter. Rare transient raises (the one observed on 2026-10-14) cannot
accumulate across preset segments.

### D3 — Doc / comment corrections

Code-side only this cycle (state-of-play was corrected in `1480811ba`):

- `hvac.py` line **~3938**: change the comment "§9.7 re-issue loop must not
  re-anchor" to "§9.9 re-issue loop must not re-anchor" (the Zone 1 away
  feed-split is now §9.9).
- `hvac.py` line **~5593**: change the docstring "the §9.7 status feed can
  misreport it" to "the §9.9 status feed can misreport it".

If the state-of-play §4.2 S10 residual bullet or §10 C37 ledger text requires
any adjustment post-review to align with Rev 2 (chiefly: "mechanism
UNVERIFIED, n=1; latch creep + snapshot poisoning are the real harms"),
apply it in the same commit as the build.

### Non-goals (explicit)

- No change to adapter verbs (`set_preset_range`, `preset_range_original`,
  `preset_range_would_write`).
- No change to `_zone_last_s1_write` shape, writer, or any of its consumers
  (`:2258-2261`, `:5304`, `:5594`).
- No change to `_zones_written_this_cycle` seeding at `hvac.py:2258-2261`
  (120 s S1 same-tick gate stays — it is a strict subset of the new gate's
  dominance region).
- No change to the ecobee adapter (D1 is a harmless upstream skip for ecobee
  zones).
- No persistence-schema change (`_s10_snapshots`, `_s10_records`,
  `.storage/universal_room_automation.hvac_zone_state` all untouched).
- No restore-pass semantics change beyond the settle gate.
- No new NM.
- No fast-path change (fast_entry / fast_exit do not call S10).

---

## Acceptance criteria (each test FAILS on today's `develop`)

### Discriminating assertions (per F6)

Each unit test is written to produce a clearly different observation under
"stale legs + landed write" vs. "unresolvable activity + rejected write" vs.
"gate active". A test whose assertions pass under the no-op baseline is a
hollow anchor and MUST be rewritten.

### Unit (`quality/tests/hvac/test_s10_post_preset_change_settle.py`, NEW)

- **T1 (D1 — gate active):** with
  `_zone_last_observed_preset_change[zone_id] = (prev, new, now - 300 s)`,
  `_s10_zone_skip_reason(zone_id, zone)` returns
  `"post_preset_change_settle"`. **FAIL on `develop`:** method has no such
  branch.
- **T2 (D1 — gate expired):** with the same stamp set to `now - 601 s`,
  `_s10_zone_skip_reason` returns None (or whatever other step fires, but
  NOT `"post_preset_change_settle"`).
- **T3 (D1 — zero wire + zero capture):** gate active; `_s10_pass(mode=
  "apply")` emits zero `strategy.set_preset_range` calls, writes zero
  `climate_write` rows, AND makes no entry in `_s10_snapshots` for the
  (zone, preset). Also assert no entry in `_s10_records[zone_id]
  [preset|apply]`. **FAIL on `develop`:** today the apply pass can call
  through step 9 and capture.
- **T4 (D1 — restore mode):** gate active, snapshot exists; `_s10_pass(
  mode="restore")` emits zero `strategy.set_preset_range` calls.
- **T5 (D1 — pre-call re-check):** stamp armed between skip-matrix check
  (`_s10_pass:4467`) and pre-call re-check (`_s10_write_one:4664`); the
  pre-call `_stand_down` is `"post_preset_change_settle"` and no wire call
  fires.
- **T6 (D1 — sibling zone unaffected):** gate active on zone_3; zone_1
  (no stamp) proceeds normally through `_s10_pass`.
- **T7 (D1 — boot with empty map):** no entries in
  `_zone_last_observed_preset_change`; `_s10_zone_skip_reason` behaves
  identically to today for every zone (NOT a global skip).
- **T8 (D1 — observed anchor covers non-S1 writer):** stamp written by
  the arrester's revert path (simulate: write to the observed map directly
  via the ZoneManager observer, without touching `_zone_last_s1_write`);
  the gate still fires. **FAIL on `develop`:** no map, no gate.
- **T9 (D2 — failure reset on APPLIED):** record has
  `failures=2, writes=0, value=V1`; value stays V1; adapter returns
  `APPLIED`; after `_s10_success` the record has `failures=0, writes=0`
  (REV 2 INV-S10-LATCH-RESET; writes reset is operator ruling A4 and
  stays). **FAIL on `develop`:** `failures` stays 2.
- **T10 (D2 — failure reset on SKIPPED_ALREADY_CORRECT):** same shape,
  adapter returns `SKIPPED_ALREADY_CORRECT`; `failures=0` after.
- **T11 (D2 — three transient raises WITHOUT D2 would latch):** on
  `develop`-with-D1-only (D2 disabled), simulate three
  FAILED/`emit_raised` across three preset segments with APPLIED writes
  between them; the record reaches `latched=True / call_failed`. With D2
  enabled, the record never latches: `failures=0` after each APPLIED.
  **FAIL on `develop`:** latch triggers at the third raise.
- **T12 (mechanism discrimination):** harness the Carrier adapter with
  (i) `current_status_activity() = None` → set attempt raises
  HomeAssistantError in-process + legs read falls back to `_status_zone`;
  (ii) `current_status_activity() != None` + stale cached
  `target_temp_{low,high}` → set attempt succeeds + legs still mismatched.
  Assert `_s10_last_outcome` distinguishes the two: (i) =
  `status="failed", reason="emit_raised"`; (ii) =
  `status="applied", reason="possible_wrong_profile"` (if adapter sets
  that) or similar. Documents the two reachable paths; both are gated
  under settle.

### Integration

- **T13:** full `_async_apply_preset_overrides` cycle with a simulated
  observed preset transition at `now - 60 s`; no `climate_write` row at
  site `S10_preset_range` for the zone; next cycle at `now + 540 s`
  (after settle expires) emits normally.
- **T14:** switch OFF → restore pass; gate active → zero restore wire
  calls; gate expired → restore proceeds (snapshot still correct).

### Sensor / outcome map

- `get_s10_diagnostics()` outcome map carries `{status: "skipped",
  reason: "post_preset_change_settle"}` for a settled tick on an eligible
  zone.

### Baseline + post-ship probe (SQL corrected per F8)

**Pre-ship baseline (run on `develop` BEFORE deploy):**

```sql
SELECT
  json_extract(details_json, '$.zone_id') AS zone,
  json_extract(details_json, '$.site')    AS site,
  COUNT(*) AS n,
  SUM(CASE WHEN json_extract(details_json, '$.wire_ok') = 0 THEN 1 ELSE 0 END) AS failed
FROM ura_activity_log
WHERE action = 'climate_write'
  AND json_extract(details_json, '$.site') IN
      ('S10_preset_range', 'S10_preset_range_restore')
  AND timestamp > datetime('now', '-14 days')
GROUP BY zone, site;
```

Correlate to preset-change rows per zone in the same window:

```sql
SELECT
  json_extract(details_json, '$.zone_id') AS zone,
  COUNT(*) AS preset_changes
FROM ura_activity_log
WHERE action = 'preset_change'
  AND timestamp > datetime('now', '-14 days')
GROUP BY zone;
```

**Post-ship (same queries 7 and 14 days post-restart):** on zone_3 the ratio
(S10 writes / preset changes) should drop meaningfully (the one 2026-10-14
pattern should not recur), AND the count of S10 FAILED/`emit_raised` rows
should be zero. On zones 1 + 2 (if rolled out in the same window), the ratio
should start at ≤ 1 and no FAILED rows should appear.

### Live

- On `develop` restart, within one full S1 cycle a preset change on zone_3
  does NOT produce a `climate_write` with `site="S10_preset_range"` for the
  following ≥ 600 s. Expect the next S10 wire attempt (if still needed) on
  the first full tick ≥ `(observed_preset_change_ts +
  S10_POST_PRESET_CHANGE_SETTLE_S)`.
- Latch store: after any APPLIED write on an existing record with
  `failures > 0`, the next persist shows `failures=0`.

### Falsifier runbook (per `feedback_falsify_before_asserting.md`)

The acceptance observation that would REFUTE the fix: any `climate_write` row
within `[preset_change_ts, preset_change_ts + S10_POST_PRESET_CHANGE_SETTLE_S]`
for the same zone with `site LIKE 'S10_%'`. The post-ship probe above surfaces
it directly.

---

## Review tier + framings

**Tier 2-DB (operator-elevated per CLAUDE.md "Operator-elevated Tier 2-DB" +
standing policy on regression-prone work).** Trust-hierarchy ripple:

- D1 introduces a new RAM observer in `hvac_zones.update_zone_climate_state`
  — a shared primitive consumed by every HVAC coordinator caller — and a new
  skip-matrix step that sits *ahead* of the existing S1 same-tick gate. A
  gate ordering mistake could silently prevent legitimate S10 restore after
  an external preset flip.
- D2 changes failure-counter semantics on `_s10_success`, which interacts
  with the §6.2 rate/latch model AND with `_s10_last_outcome` consumers in
  diagnostics.
- Mechanism is still PARTIAL (n=1); the plan is right to be conservative.

Three framing-disjoint reviews **in parallel**, each with a distinct focus
area (no overlap in blind spots):

- **Review A — correctness + edge cases.** The settle predicate; skip-matrix
  ordering (settle vs. the pre-existing `s1_same_tick`, `egress_paused`,
  `person_protected`, `borrow_live`, `ac_reset`); observer behaviour when
  `preset_mode` and `hold_activity` disagree mid-transition; pre-call
  re-check path; the `failures` reset in `_s10_success` not clobbering
  anything downstream (`_s10_latch`, `_s10_note_outcome` consumers,
  diagnostics / NM); ecobee no-op path; D-LOW-2 generation guard still
  correct.
- **Review B — cross-coordinator + lifecycle + migration integrity.**
  Boot/reload with empty observed map; a transition observed mid-await; a
  user toggle of switch 01 during settle; interaction with the arrester's
  own `SUPPRESS_TTL_SECONDS_PRESET` (climate-entity side, 120 s —
  deliberately not shared); interaction with the Bryant schedule flipping a
  preset on zones 2/3; migration: no persisted state changes, but confirm
  the latch store rows with `failures > 0` get discharged correctly on the
  first APPLIED post-upgrade (not retroactively latched); verify no
  double-dispatch of a `preset_change` ledger row.
- **Review C — new surfaces + test fixture authority + adversarial
  completeness (per F6).** Verify every acceptance test above actually
  fails on `develop` (via per-site source mutation, not aggregate monkeypatch
  — `feedback_hollow_test_anchors.md`); re-enumerate every S10 wire site AND
  every writer that mutates `preset_mode` / `hold_activity` on a Carrier
  zone (independent of the plan's list); state the falsifiable invariant in
  its own words and attempt to break INV-S10-SETTLE and INV-S10-LATCH-RESET
  from any reachable path including pre-existing code (not just the diff);
  verify `get_s10_diagnostics()` round-trips the new outcome row.

**Plan review:** per CLAUDE.md Tier-2+ plan-review protocol, ONE adversarial
plan review before build dispatch (Rev 2 itself is the response to the Rev 1
plan review; another plan-review pass of Rev 2 is required before build).

---

## Doc corrections required (apply in same commit as build)

The state-of-play corrections from Rev 1 shipped in commit `1480811ba`
(C37, §4.2 UNVERIFIED marker, 5 "not deployed" labels filled, duplicate
§9.7 renumbered to §9.9). Remaining items for this cycle:

1. **`hvac.py` ~line 3938 comment:** `§9.7` → `§9.9`.
2. **`hvac.py` ~line 5593 docstring:** `§9.7` → `§9.9`.
3. If Review B/C find a wording residual in state-of-play §4.2 or §10 C37
   after Rev 2 is approved, patch it in the same build commit.

---

## Open questions

- **Q1 — ecobee interaction.** The ecobee adapter stores URA-side ranges
  (`effective_range` is the oracle; W1-C P2 build note); the gate is a
  harmless upstream skip. No adapter branch needed, but Review A verifies
  no observable behaviour change on ecobee zones.
- **Q2 — Bryant schedule-driven transitions on zones 2/3.** The observer
  anchors on the OBSERVED preset-mode / hold-activity transition, so a
  Bryant schedule flip arms the settle just like a URA write. This is
  correct (the stale-read window exists irrespective of writer), but
  Review B confirms no runaway re-arming on schedule chatter.
- **Q3 — Window length revisit.** 600 s is the measured upper bound + a
  ~180 s jitter margin, n=1. If post-ship probe shows p99 stale-window ≥
  500 s across ≥ 10 preset changes, raise to 900 s. If p99 < 300 s across
  ≥ 50 preset changes, drop to 450 s. Document the decision in the Rev 3
  of this plan or in a follow-up card; do not change silently.
- **Q4 — AC-reset preset writes.** `_restore_after_reset` /
  `_verify_restore` can flip the preset via the arrester, not S1. Rev 1
  scoped this out; Rev 2's observer anchor **covers it** by construction
  (any observed `preset_mode` change arms the window). No further action.

---

## Build sequence (for the builder, not this cycle)

1. Add `S10_POST_PRESET_CHANGE_SETTLE_S = 600` to `hvac_const.py` with the
   comment block above.
2. Add `_zone_last_observed_preset_change: dict[str, tuple[str | None,
   str | None, datetime]]` to `HVACCoordinator` (init in `__init__` next
   to `_zone_last_s1_write`) and `_note_observed_preset_change(zone_id,
   prev, new, ts)` helper.
3. In `hvac_zones.ZoneManager.update_zone_climate_state`, immediately
   after the `preset_mode` / `hold_activity` refresh, if either changed
   from the previous RAM copy call `coordinator._note_observed_preset_change(
   zone_id, prev_preset, new_preset, utcnow())`.
4. Extend `_s10_zone_skip_reason` with the `post_preset_change_settle`
   check inserted between step 0.5 and step 1.
5. In `_s10_success`, add `rec["failures"] = 0` next to `rec["writes"]
   = 0`.
6. Patch the two §9.7 → §9.9 comment references in `hvac.py` (~3938,
   ~5593).
7. Add unit tests in `quality/tests/hvac/test_s10_post_preset_change_settle.py`
   (T1-T12 above).
8. Run `.venv-ha/bin/python -m pytest quality/tests/hvac/ -k "s10 or
   preset_range or preset_change" -v`.
9. Run the baseline probe SQL on `develop` immediately before deploy; stash
   the result in the README. Re-run 7 and 14 days post-restart; record both
   in the README validation table.

---

## Report (for the parent orchestrator)

- **Chosen shape:** operator shape **(a) + (b)**. (b) is the primary fix
  (D1 observed-preset-change settle gate, 600 s, OWN constant); (a) is the
  orthogonal correctness fix (D2 reset `failures` on
  `_s10_success`). Marginal cost of adding (a) on top of (b) is one line;
  the pair closes BOTH the latch creep AND the snapshot-poisoning risk on
  zones 1+2 rollout, which (b) alone does not fully close against a
  longer-than-measured transition.
- **Tier:** **Tier 2-DB (operator-elevated)** — trust-hierarchy ripple into
  the zone-state observer + the failure-counter / latch semantics + the
  snapshot-capture path; mechanism is PARTIAL (n=1). Three framing-disjoint
  reviews (A=correctness, B=cross-coordinator+lifecycle+migration,
  C=new-surfaces+test-authority+adversarial-completeness) in parallel + a
  plan-review of Rev 2 before build dispatch.
- **Invariant:** **INV-S10-SETTLE** (zero wire call, zero snapshot capture,
  zero failure increment for Z while an observed preset transition is less
  than `S10_POST_PRESET_CHANGE_SETTLE_S` old) PLUS **INV-S10-LATCH-RESET**
  (every APPLIED / SKIPPED_ALREADY_CORRECT resets `rec["failures"] = 0`).
- **Mechanism marker:** PARTIAL / UNVERIFIED (n=1). Both reachable paths —
  stale legs + landed write (hypothesised) and unresolvable activity +
  rejected write (observed once) — are gated by D1. Acceptance tests T12
  discriminate the two.
- **Measurement completed before plan:** yes (2026-10-15 probe, 3 S10
  writes since 10-13; 1 failure; 422 s stale window; 1/544 base rate; no
  snapshot poisoning yet; latch store `failures=1`).
- **Unresolved / deferred:**
  - **Q3 window-length tuning** post-ship. Convert to a code trip-wire if
    p99 stale-window ever exceeds the configured value (anomaly in
    `_s10_zone_skip_reason` ↔ settle-expired-but-still-stale), rather than
    scheduling a soak watch (`feedback_no_soak.md`).
  - **Rev 1 withdrawal** carried a potential ambiguity in the state-of-play
    §4.2 S10 residual bullet (Rev 1's "stale status-feed read; redundant
    wire call per preset change" wording). Commit `1480811ba` already marked
    this UNVERIFIED; if Review B/C request further wording adjustments to
    align with Rev 2's two-path mechanism, patch in the same build commit.
  - **Mechanism remains n=1.** This plan does not wait for a second
    occurrence (the latch creep + the zones 1+2 snapshot-poisoning risk are
    sufficient justification), but a Review C adversarial pass may elect to
    harvest additional recorder evidence from the ha_carrier logbook before
    final sign-off.
- **Not changed in this cycle (explicit non-goals):** adapter verbs;
  `_zone_last_s1_write` surface; `_zones_written_this_cycle` seed;
  persistence schema; ecobee adapter; NM channels; fast-path.
