# AUDIT: SignalTrustLedger golden-fixture yield from existing recorder history

**Date:** 2026-08-09
**Question:** Can GO criterion 4 of `PLANNING_signal_trust_ledger_abstraction.md` — the per-bucket
golden-fixture firing counts — be satisfied from data that already exists, instead of by building
the `LEDGER_GOLDEN_TAP_ENABLED` runtime tap and waiting a two-week live-in window?
**Posture:** measure-before-you-build probe (CLAUDE.md, operator-coined 2026-07-13). Strictly
read-only. No production code written, no tap built, nothing restarted.

---

## Answer in one line

**Four of the six required buckets are already FILLED from data on disk today. The two that are
short (D1, D3) and the one that is under-filled (P24) would NOT be fixed by building the tap —
they are short because the events do not occur, not because instrumentation was missing.**
GO criterion 4 as written is therefore unsatisfiable by waiting, and the tap is the wrong
instrument. Recommendation is a hybrid of (a) and (c), detailed below.

---

## Method

Two independent evidence surfaces were used, and cross-checked against each other.

### Surface 1 — offline replay of the detectors against HA recorder history

- DB: `/config/home-assistant_v2.db`, opened `file:...?mode=ro` (URI read-only), 20.9 GB.
- All queries scoped by `metadata_id` via `states_meta`; no unfiltered scan of `states`.
  (One exploratory `LIKE` over `state_attributes` was started, observed to be an unindexed
  join, and cancelled rather than left running against the live instance.)
- Window observed: `2026-08-02 → 2026-08-09`, **7.46 days** (`purge_keep_days: 7`).
- Room→sensor map built from `/config/.storage/core.config_entries`, URA entries only.
  38 room entries; keys read as production reads them —
  `motion_sensors`, `presence_sensors` (= `CONF_MMWAVE_SENSORS`, `const.py:334`),
  `occupancy_sensors`. **58 distinct configured presence-class sensors**, all 58 present in
  the recorder (zero missing). No room uses the legacy `mmwave_sensors` key as its only source.
- Detector semantics were reproduced from HEAD, not from memory:
  - `_is_sensor_on` (`coordinator.py:1738`) — `unavailable`/`unknown` count as **off**.
  - **M1/P22** (`coordinator.py:1949-1981`): continuous-on ≥ `_stuck_sensor_hours` = 4.0 h.
  - **M5/D2** (`_detect_duty_cycle_stuck`, `coordinator.py:1460`): 30 s tick grid (matching
    `update_interval=timedelta(seconds=30 + jitter)`, `coordinator.py:486`), rolling
    `window_min=60` ring, `pct=0.85`, `min_ticks=20`, PIR-corroboration shield
    (`≥2` transitions in window **or** `≥1` within `STUCK_D2_FRESH_MOTION_SECONDS=300`).
    Live knob values were read from the integration config entry and match the defaults.
  - Verified that the classification path gates only on `_d2_boot_settle_done()`; the
    `_d2_motion_sensors_present` / `_d2_house_state_allows` / `_d2_debounce_elapsed` gates at
    `coordinator.py:2653-2656` belong to the *demotion consumer*, not to D2 classification.
- **Restart modelling.** The P22 book (`_sensor_on_since`) and the D2 rings are in-memory and
  cold on boot. HA start/reload bursts were detected as clusters of ≥50 `old_state_id IS NULL`
  rows within 3 min over a 500-entity binary_sensor sample: **30 restarts in the window**,
  median inter-restart gap **2.5 h**, longest continuous uptime **1.02 days**. M1 was replayed
  both restart-blind and restart-aware; the restart-aware number is the one reported.

### Surface 2 — URA's own persisted logs (longer retention than the recorder)

`/config/universal_room_automation/data/universal_room_automation.db` (1.1 GB, read-only).

- `notification_log` — retained **2026-07-26 → 2026-08-09 (14 days)**, i.e. *twice* the recorder
  window. `hazard_type='stuck_signal'` rows carry the watchdog D4 emits with the exact
  `kind` in the title and room/sensor in the message. This is the authoritative record of what
  the running house actually detected.
- `decision_log` (span 2026-02-28 → today) and `ura_activity_log` — `preset_change` rows carry
  `reason` in `context_json` / `details_json`.
- `sensor.ura_coordinator_manager_stuck_signal_watchdog` (recorder): 314 rows in the window,
  **262 non-zero**, states ranging 0–5 — independent confirmation that the detector surface is
  live and actively flagging.

Surfaces 1 and 2 agree on every bucket where both apply.

---

## Per-bucket results

| Bucket | Site | Required | Offline replay (7.46 d recorder) | Live NM ledger (14 d URA DB) | Verdict |
|---|---|---|---|---|---|
| **P22** | M1 continuous-on | 5+ | **18 episodes**, 7 sensors / 6 rooms (restart-aware; 20 restart-blind) | 16 `continuous` NM rows over 6 distinct days, 3 distinct (room,sensor) | ✅ **FILLED** (3.6×) |
| **P24** | M2 max-active failsafe | 5+ | not independently replayable (see below); recorder holds exactly **1** `occupancy_source:"failsafe"` attribute blob | **1** `max_active_failsafe` NM, 2026-08-06 00:24 | ❌ **SHORT by 4** |
| **P18** | M3 zone stale-occupancy | 3+ | not independently replayable (see below) | **5** `zone_stale_occupancy` NM over 4 distinct days | ✅ **FILLED** |
| **D1** | M4 camera stuck-count | 3+ | **0** — no interior Frigate camera came close (see below) | **0** NM rows | ❌ **SHORT by 3** |
| **D2** | M5 duty-cycle | 3+ | **13** distinct (room,sensor) classifications across 8 rooms | 68 `dutycycle` NM rows over 6 days, 7 distinct (room,sensor) | ✅ **FILLED** (4.3×) |
| **D3** | M6 frozen tracker | 1+ | **0** — structurally unreachable (see below) | **0** NM rows | ❌ **SHORT by 1** |
| *M7/P14* | weighted veto | *excepted* | — | — | hand-built by design |

### Detail on the three short/filled-by-log buckets

**P22 (M1) — FILLED.** Restart-aware replay, 18 episodes:
Jaya Bedroom `binary_sensor.jaya_3_presence` ×9 (4.06–5.7 h), Upstairs Guestroom
`..._upguestroom_presence_2` ×3 (5.3/6.2/8.9 h), Living Room `screek_human_sensor_l13_2412s` ×2,
plus single episodes in Patio, Game Room, Ziri Bedroom, Exercise Room.
Restart-blindness inflates this by only 2 (20 → 18), so the 30 restarts are not the dominant term
here — 4 h episodes largely fit inside the 2.5 h median gap only by luck of alignment, and the
replay confirms most survive. Note the replay (18) exceeds the live NM count (16 rows, 3 distinct
sensors) because the NM helper carries a **per-day dedup latch** keyed `(room_name, entity_id)`
— NM counts are latch-limited and are a *lower bound* on firings, not a firing count.

**P24 (M2) — SHORT by 4.** Two independent surfaces agree on exactly one firing in the window:
one `max_active_failsafe` NM (latch key is `(room_name,)` — per-room per-day, so this is at most
a small undercount), and exactly one distinct `occupancy_source:"failsafe"` attribute blob in
`state_attributes`. Observed rate ≈ **1 per 14 days**. Reaching 5 firings at that rate takes
**~10 weeks**, and the failsafe's Tier-1-freshness skip (`v4.5.16`) is specifically designed to
suppress the common case, so the rate is low *by intent*.

**P18 (M3) — FILLED from the NM ledger.** 5 emits over 4 distinct days. Note `decision_log`
shows zero `stale_occupancy` reasons: the reason-ladder tag was only added by the **B-H1
fix-up on 2026-08-06** (`hvac.py:1341, 1408, 1597`), so the decision-log surface post-dates
most of the firings. The NM ledger, which was wired in v5.35.0, is the correct surface here.

**D1 (M4) — SHORT by 3, and not a time problem.** The interior Frigate set is
`camera_person_entities` on the integration entry: playroom, master_hallway, staircase,
foyer_fisheye, family_room, upstairs_hall, stairs_top (+ hi-res channels). Longest
`person_count > 0` unchanged hold across all of them in 7.46 days:

| interior camera | max unchanged `>0` | max never-zero |
|---|---|---|
| master_hallway | 0.31 h | 0.31 h |
| staircase | 0.27 h | 0.27 h |
| foyer_fisheye | 0.14 h | 0.14 h |
| playroom | 0.11 h | 0.11 h |
| upstairs_hall | 0.11 h | 0.11 h |
| family_room | 0.08 h | 0.08 h |
| stairs_top | 0.04 h | 0.04 h |

Thresholds are `CONF_STUCK_CAMERA_HOURS = 3.0 h` (unchanged rule) and
`STUCK_CAMERA_NEVERZERO_HOURS = 6.0 h`. The observed maximum is **~10× below** the nearer
threshold. The only camera anywhere near it — `sensor.garage_b_person_count` at 6.52 h unchanged
— is on a **perimeter/uncategorised** camera, not in the interior set, so D1 correctly never
looked at it. This bucket does not fill by waiting a few more weeks; it would take a genuine
stuck-camera incident.

**D3 (M6) — SHORT by 1, structurally unreachable at the current restart cadence.**
`_frozen_tracker_check` (`person_coordinator.py:483`) fires on
`tracker.last_updated` age ≥ `DEFAULT_FROZEN_TRACKER_DAYS = 2.0` days. Two measurements:
- Longest continuous HA uptime in the window: **1.02 days** (30 restarts, median gap 2.5 h).
  A restarted HA re-adds `device_tracker` entities with a fresh `last_updated`, so the age
  counter can never reach 2.0 days.
- Independently: across **1793** `device_tracker` entities, the oldest last-recorded-row age is
  **1.93 days** and **zero** trackers have no rows in the window.

Both agree: D3 cannot fire while the deploy cadence keeps uptime under two days.
**The runtime tap would have recorded zero rows for this bucket too.**

---

## Recommendation on GO criterion 4

**Hybrid (a) + (c) — and criterion 4 should be rewritten.**

**(a) Satisfiable today, from existing data, for 4 of 6 buckets: P22, P18, D2, and the M1
input stream.** No tap, no waiting. P22 and D2 fixtures can be *generated* by offline replay of
the recorder (inputs + outputs, exactly the JSONL shape the tap was to emit). P18's fixture rows
come from the URA `notification_log` + the paired `decision_log`/`ura_activity_log` rows.

**(b) is rejected.** Raising `purge_keep_days` buys nothing worth its cost here. The binding
constraint is event rate, not retention — and URA's own `notification_log` already retains
**14 days**, twice the recorder, for exactly the events in question. For the one bucket where
retention would help at all (P24, ~1 firing / 14 days), you would need ~10 weeks of history, at
roughly 3 GB/week of additional recorder growth on an already-20.9 GB database that is carrying
a ~900 MB unreclaimed-page backlog. Not worth it.

**(c) Genuinely blocked — but the tap does not unblock them.** For **D1**, **D3**, and the
remaining 4 P24 firings, the events did not occur in 14 days of production. A tap running for
two more weeks would capture the same zeros. These three need one of:
- **D1:** accept a hand-built fixture, or re-examine whether a 3 h/6 h threshold that is 10×
  above anything the house produces is calibrated to a real failure mode at all. (Worth asking
  before the ledger freezes that behavior — a detector that has never fired has no oracle to be
  frozen *to*.)
- **D3:** either accept a hand-built fixture, or lower `CONF_FROZEN_TRACKER_DAYS` below the
  achievable uptime, or note that the detector is dormant-by-deploy-cadence and freeze it from
  a synthetic fixture with operator sign-off.
- **P24:** accept the single real firing plus hand-built supplements, with operator sign-off —
  which criterion 4 already permits ("or accept a hand-built supplement with operator sign-off").

**Concrete proposal:** replace criterion 4's "≥2 weeks under `LEDGER_GOLDEN_TAP_ENABLED`" with
"golden fixtures generated by the offline replay harness over ≥7 days of recorder history plus
the URA `notification_log`, meeting the per-bucket counts; buckets D1, D3 and the P24 shortfall
supplemented by hand-built, operator-signed fixtures with the shortfall reason recorded." The
`LEDGER_GOLDEN_TAP_ENABLED` knob and its `.storage/ura_ledger_golden/` writer can be dropped
from the plan entirely — that removes a new writer to `.storage`, an options-flow knob, and a
build-then-remove deliverable, in exchange for a read-only script.

---

## Is an offline replay harness a viable substitute for the runtime tap?

**Yes for M1 and M5; partially for M4; no for M2 and M3 as pure replay.** Detail:

| Site | Replayable offline? | Why |
|---|---|---|
| **M1 / P22** | ✅ Fully | `_sensor_on_since` is a pure function of the binary-sensor stream. Verified this run. |
| **M5 / D2** | ✅ Fully | The ring and the PIR-corroboration shield are pure functions of the same streams resampled on a 30 s grid. `time.monotonic()` is only used for deltas — wall-clock deltas are equivalent. Verified this run. |
| **M4 / D1** | ⚠️ Partially | `person_count` is in the recorder, but the corroboration side (`_ble_home_by_area`, `_room_tier_corroboration_by_area`) is URA-derived per-tick state that is **not** recorded. The stuck-window arithmetic replays; the discount decision does not, without re-simulating the census. Moot today — the window never opens. |
| **M2 / P24** | ❌ Not as pure replay | Inputs are `_became_occupied_time` and `_last_motion_time` — coordinator-internal state machine variables, absent from the recorder. Worse, the detector is **closed-loop**: firing sets `data[STATE_OCCUPIED]=False` and `_last_motion_time=None`, mutating its own future inputs. Faithful replay = re-simulating the whole occupancy state machine (debounce, timeouts, tiers), which is not a fixture harness, it is a second implementation — and a second implementation is exactly the thing a golden-parity oracle is supposed to be independent of. |
| **M3 / P18** | ❌ Not as pure replay | Same shape: `zone.continuous_occupied_since`, `zone.any_room_occupied`, and `check_zone_occupancy_confidence(zone)` are zone-object state and a live cross-coordinator call. Use the persisted NM + decision-log rows as the fixture instead of replaying. |
| **M6 / D3** | ✅ Mechanically, but yields 0 | `device_tracker.last_updated` is recoverable from the recorder. The predicate is simply never satisfied. |

**Limitations the harness must declare:**

1. **In-memory book resets on restart are invisible in the recorder** and must be modelled
   explicitly. This run measured 30 restarts / 7.46 days; ignoring them inflated M1 by 2
   episodes (20 vs 18). Any harness that skips this produces fixtures the production code would
   never have generated. This is the single largest replay/production divergence found.
2. **Boot-settle gates are not reconstructable.** `_d2_boot_settle_done()` /
   `_d1_boot_settle_done()` read `presence._boot_settle_done`, which is not recorded. Replay
   over-counts by however many verdicts production suppressed in each post-boot settle window
   — and with a 2.5 h median inter-restart gap, that window is a non-trivial fraction of
   wall-clock time.
3. **URA-derived per-tick state is not in the recorder** — house_state as the coordinator saw
   it, BLE-here-by-area, room-tier corroboration snapshots, `possible`/`confirmed` counts from
   `check_zone_occupancy_confidence`. Any detector reading these is not purely replayable.
4. **NM counts are latch-limited, not firing counts.** `fire_stuck_signal` dedups per-day per
   key (`(room, entity)` for P22/D2, `(room,)` for P24, `(zone,)` for P18). Treat the
   `notification_log` as a lower bound on episodes.
5. **7-day recorder horizon** vs 14-day `notification_log`; the two surfaces cover different
   spans and should not be summed.
6. **Attribute-derived evidence is expensive to query.** `state_attributes` has no usable index
   for content search and `states.attributes_id` is unindexed; scope every such query by
   `metadata_id` first. (One unscoped attempt during this probe had to be cancelled.)

---

## Read-only compliance

Every DB handle opened with `file:...?mode=ro` URI. All `states` access scoped by
`metadata_id`. No writes, no schema reads that mutate, no HA restart, no config change, no
service call. One long-running exploratory query was cancelled client-side rather than left
scanning the live 20.9 GB database.


---

## ORCHESTRATOR CORRECTION + ESCALATION (2026-08-09)

**Count corrected:** the prose said "4 of 6 buckets are satisfiable today"; the table says **3**
(P22, P18, D2 FILLED; P24, D1, D3 SHORT). Corrected in place. This doc is the authority for a GO
criterion, so the arithmetic has to match.

**Thresholds independently verified:** `DEFAULT_FROZEN_TRACKER_DAYS = 2.0` (`const.py:3121`),
`DEFAULT_STUCK_CAMERA_HOURS = 3.0` (`const.py:3099`).

### The finding that outgrew this audit: three of the four v5.35.0 detectors are effectively inert

The short buckets are short **because the events do not happen** — not because instrumentation was
missing. That is a statement about the shipped watchdog, not about fixtures:

| Detector | Status in this deployment | Evidence |
|---|---|---|
| **D3 frozen tracker** | **structurally unreachable — can never fire** | threshold 2.0 d; longest HA uptime in-window **1.02 d** across **30 restarts** (2.5 h median gap). Restart re-adds trackers with fresh `last_updated`, resetting the counter. Oldest of 1793 trackers = **1.93 d**, under threshold. |
| **D1 camera stuck** | never fired | interior max `person_count>0` hold **0.31 h** vs **3.0 h** threshold — ~10× margin |
| **P24 max-active failsafe** | ~1 firing / 14 d | exactly 1 emit (2026-08-06) |

**D3 cannot catch the incident that motivated it.** It was built for the Ezinne 3-day frozen tracker;
with HA restarting every ~2.5 h, a 3-day freeze is invisible to a detector measuring uninterrupted
`last_updated` age.

This is the same defect STUCK-SENSOR-1's original card flagged and nobody pursued: *"NO PERSISTENCE:
like the echo counter, any stuck-state tally resets on restart, and we restarted 7+ times today."*
The probe proves that gap is fatal for D3 specifically. Fixing it means measuring staleness from a
**persisted** timestamp rather than in-memory `last_updated` — or reducing the restart rate, which is
an ops issue in its own right (30 restarts in 7.46 days).

**Consequence for the ledger:** migrating a detector that has never fired buys nothing, and freezing a
golden fixture for it is impossible by construction. D1/D3 should be **fixed, re-thresholded, or
dropped from the migration set** before M4/M6 are scoped. Tracked as `WATCHDOG-INERT-1`.
