# PLANNING — Census Accuracy (interior)

**Card:** `CENSUS-ACCURACY-1` (Kanban 2026-08-17)
**Scope:** INTERIOR census accuracy. Two core deliverables + one small
exterior-dashboard bonus. Not guest policy (shipped v5.79.0). Not code
dedup repair (probe rejected). Not exterior census swap (KEEP BOTH ruling).
**Probe already run:** `docs/planning/AUDIT_census_accuracy_probe.md`
(commit 4f67edfea) — measurement-first gate; results wired into the
Go/No-Go per deliverable below.
**Adjudication read:** `docs/planning/AUDIT_exterior_census_supersession.md`
(commit eb2caa3c8) — KEEP BOTH.

---

## 0. Institutional Context Verified

### 0.1 Prior planning docs / research consulted (full read)

| Doc | Relevance |
|---|---|
| `docs/planning/RESEARCH_census_vs_guest_separation.md` | Authoritative separation-of-concerns synthesis. §2 = the decay ruling. §2.5 documents that `CensusHoldDecayService` (v4.7.18 D1) and `peek()` (D5) were designed and NEVER BUILT. §5 change #5 = "delete the linear decay slope on the house zone; adopt the property zone's instant-drop". |
| `docs/planning/PLANNING_v4.7.18_census_service_shared_refactor.md` | D1 (`CensusHoldDecayService`) + D5 (`peek()`) planned, not shipped. This cycle DELIBERATELY does NOT extract a service — see §7 non-goals; we edit in place at `camera_census.py:2516-2637`. |
| `docs/planning/AUDIT_census_accuracy_probe.md` | 74.5%/12.83h of elevated time = pure decay tail. Fresh-face fired 0x/7d. Dedup repair buys ~0 (area-set disjoint). |
| `docs/planning/AUDIT_exterior_census_supersession.md` | KEEP BOTH: `persons_on_property_exterior` (naive) NOT overwritten. Dashboard headlines the linker's already-live `exterior_person_tracks_active` with G1 fallback. |
| `docs/planning/PLANNING_guest_census_correctness.md` (rev-2, shipped v5.79.0) | Review B has the consumer enumeration for `unidentified_count` / `identified_count` — REUSED here rather than re-enumerated. |
| `docs/planning/AUDIT_census_accuracy_regression.md` | `_2`-suffix migration audit; source of `_has_any_suffix_stripped` precedent (`camera_resolver.py:317-327`). |

### 0.2 Design docs / coordinator docs

- `docs/Coordinator/` — no `PersonCensus` doc exists (`PersonCensus` is not a
  domain coordinator; it is a service in `camera_census.py`). Presence
  design doc is out of scope: this cycle does not touch presence.

### 0.3 Code surveyed end-to-end

- `custom_components/universal_room_automation/camera_census.py:2496-2680`
  (hold/decay + pending latch state machine); `:2720-2810`
  (`_get_unrecognized_camera_count` per-camera face lookup); `:3031-3110`
  (`_get_face_recognized_person_names` per-person `frigate_*_last_camera`
  lookup); `:1178-1210` (`SIGNAL_CENSUS_UPDATED` dispatch payload);
  `:2383`, `:2399`, `:2432`, `:2752` (all four face_sensor_id
  construction sites).
- `custom_components/universal_room_automation/camera_resolver.py:284-332`
  (`_strip_disambiguation_suffix`, `_has_any_suffix_stripped`,
  `_prefer_canonical`).
- `custom_components/universal_room_automation/sensor.py:3411-3530`
  (`_CensusBaseSensor` + `persons_in_house` attrs, already publishes
  `peak_held` / `peak_age_minutes`); `:3615-3649`
  (`URAPersonsOnPropertySensor`, naive exterior, KEEP); `:3849-3928`
  (`exterior_person_tracks_active` + linker-fed sensors, KEEP as
  headline source for the dashboard change).
- `custom_components/universal_room_automation/domain_coordinators/presence.py:4323`
  (`_handle_census_update`), `:5354-5390` (v5.79.0 D3 precedent for
  registry-resolve-by-unique_id).

### 0.4 REUSED / NEW per proposed addition

| Proposed | Verdict | Justification |
|---|---|---|
| Instant-drop after hold on the house zone | **REUSED** | Branch already written and running for property zone at `camera_census.py:2633-2637`. We delete `:2621-2632` (the linear slope) and reuse the property branch symmetrically. |
| Kill the peak self-refresh on `fresh == peak` | **REUSED (delete-only)** | The refresh site is a single call at `camera_census.py:2601-2605`. No new mechanism. |
| `peak_held` / `peak_age_minutes` / `count_as_of` on the dispatch payload | **PARTIAL REUSE** | `peak_held` + `peak_age_minutes` are already returned by `_apply_hold_decay` (`:2521`) and already published on the sensor attrs (`sensor.py:3496-3497, 3647-3648`). NEW: add them to the `SIGNAL_CENSUS_UPDATED` payload (`camera_census.py:1195-1210`) + a `count_as_of` ISO timestamp so consumers can distinguish held-vs-fresh without re-reading the sensor. |
| `peak_refresh_count` diagnostic attr | **NEW** | Probe §Q4 CONFIDENCE explicitly asks for this to make self-refresh directly measurable. Adds ~3 LoC on the state machine + one attr. |
| Registry-resolve face + last_camera sensors | **REUSED** | Precedent `presence.py:5354-5390` (v5.79.0 D3, `entity_registry.async_get_entity_id(..., unique_id)`); helper `_strip_disambiguation_suffix` at `camera_resolver.py:291`. NEW code = ~40 LoC applying the pattern at 4 face sites + 1 last_camera site. No new constants. |
| `CONF_CENSUS_HOLD_INTERIOR` change 3 → 1 min | **REUSED (config only)** | Already a rung-2 config key at `const.py:2679`. Post-deploy Number/options change, not a code change. |
| Exterior dashboard swap | **PWA / config only** | `exterior_person_tracks_active` (`sensor.py:3849`) already live. No URA-side code change. |

### 0.5 Memory bodies pulled

- `feedback_measure_before_build.md` — probe is done; this plan is gated on it.
- `feedback_hollow_test_anchors.md` — every test below drills by DETACHING
  the value, not by grepping the source.
- `feedback_suppression_needs_discharge.md` — deleting the peak-refresh is
  a suppression; the discharge is the natural downward path (fresh < peak →
  hold expiry → instant drop). Restart resets peak (in-memory), which is
  the acceptable backstop.
- `feedback_no_fabrication.md` — every line above cites file:line.

---

## 1. Tier Classification — **Tier 2-DB (3 framing-disjoint reviews)**

**Argument.** Census is a shared primitive consumed by
presence / house-state / guest / security / HVAC / NM (see v5.79.0
Review B consumer list, ~18 trust decisions). Per the standing policy in
`CLAUDE.md`:

> use the Tier 2-DB review protocol — 3 framing-disjoint reviews — for
> ALL regression-prone work

D1 (decay) changes the semantics of a number every one of those consumers
already reads. D2 (registry-resolve) changes the value of `identified_count`
under normal operation. The failure mode is silent: a wrong count that
LOOKS the same shape as a right one. This is the exact class the 3-framing
protocol exists for. Explicit tier — **Tier 2-DB**.

Three framings (locked; parallel; different explicit focus so blind spots
cannot converge):

- **A — Correctness + edge cases (decay semantics).** Fresh vs held paths;
  pending-latch interactions with peak-refresh deletion; boundary at the
  hold-expiry instant; empty-house window (all four residents away, no
  cameras firing) — does the count reach 0 and STAY 0? Byte-identity on the
  no-op path (no live camera).
- **B — Registry-resolve integrity + cross-consumer payload shape.**
  Registry lookup at 5 sites; `unique_id` conventions for Frigate face +
  `frigate_*_last_camera`; behavior when the sibling entity is truly
  missing (must fail-CLOSED = no free `-1` credit, not fail-OPEN); payload
  shape change on `SIGNAL_CENSUS_UPDATED` — every consumer at
  `_handle_census_update` sites still reads what it expects, additive only.
- **C — Test authority + observability.** Every anchor drills by DETACHING
  the value (delete `peak_held` from payload → does a specific test go red?
  neuter the registry lookup → does a specific test go red? mutate the
  hold-expiry branch → does a specific test go red?). No monkeypatch-only
  proofs. Live-validation criteria must DISCRIMINATE the fix from a
  plausible OTHER failure (e.g. "count went to 0" is not enough — it must
  go to 0 within the empty-house-plus-1-detector-cadence window AND not
  climb back on the next tick).

**No operator elevation to Tier 3** — the falsifiable invariant is
tightly bounded (one state machine, one number), no state-machine ×
time-seam ingredient, no cross-coordinator ripple beyond a payload
additive extension.

---

## 2. Falsifiable Invariants (up front)

Each invariant is stated in a form a plausible DEFECT would violate. The
v5.79.0 lesson (INV-GUEST-LEAD was satisfied by a real defect) is the
reason each one is paired with a discriminating live observation.

- **INV-DECAY-HONEST.** *For every census tick, if no live interior
  camera has asserted a body for the last `hold + 1 tick`
  ( ≤ 4 min under current defaults, ≤ 2 min after post-deploy Number
  tuning to 1 min ), then `persons_in_house.unidentified_count` is 0 AND
  `peak_held` is False.* Violated by: any decay slope, any peak self-
  refresh, any held tail longer than `hold + 1 tick`.
- **INV-PEAK-NO-SELF-REFRESH.** *For every census tick, `peak_ts` is
  only ever written on a strict upward promotion (pending → peak) or on
  a downward reset-to-fresh at hold-expiry. `fresh == peak` MUST NOT
  refresh `peak_ts`.* Directly falsifiable by drilling
  `_apply_hold_decay` with a steady fresh sequence and asserting
  `peak_ts` is unchanged after N ticks.
- **INV-FRESH-FACE-RESOLVES.** *For every configured Frigate person
  camera whose face sensor is registered in `entity_registry`, the
  census resolves its `*_last_recognized_face` entity_id via the
  registry (not by string construction). If the sensor is absent from
  the registry, the code fails CLOSED (no `-1` credit) and increments a
  new `face_lookup_missing` diagnostic counter.* Falsifiable by
  registering a face sensor with the `_2` suffix and asserting the
  cycle's canonical resolution returns the `_2` entity_id (not the
  non-existent un-suffixed one).
- **INV-PAYLOAD-DISCRIMINABLE.** *Every `SIGNAL_CENSUS_UPDATED` payload
  carries `peak_held`, `peak_age_seconds`, and `count_as_of` (ISO).* A
  consumer reading the payload can always tell whether the count is an
  observation or an echo.

---

## 3. PRODUCER + CONSUMER check for the count (mandatory)

### 3.1 PRODUCER (how `unidentified_count` / `identified_count` are made)

Two derivations, ENHANCED wins:

- **Raw / subtractive** — `_cross_correlate_persons` `camera_census.py:1746-1818`. Structurally
  enforces one-person-one-count. Computed every tick, then discarded when
  enhanced path is on.
- **Enhanced / additive (default ON)** — `_apply_enhanced_house_census`
  `camera_census.py:3075-3137`:
  1. `unidentified_raw = camera_unrecognized`
     (`_get_unrecognized_camera_count`, `:2670-2810` — the per-camera
     `-1` face defence lives here; **currently returns 0 credits** because
     the constructed `sensor.<base>_last_recognized_face` doesn't exist —
     probe Q3).
  2. `held_unidentified = _apply_hold_decay(raw, "house", now)`
     (`:2516-2637` — the state machine that self-refreshes on
     `fresh == peak` at `:2601-2605`; this is the 74.5% cost).
  3. `identified_count = len(ble_persons ∪ face_recognized)` where
     `face_recognized = _get_face_recognized_person_names` (`:3031-3110`,
     constructs `sensor.frigate_<slug>_last_camera` — **also
     mismatches live registry**; every value in the union comes from BLE
     today).
  4. `total = identified_count + held_unidentified`.

**Each dependency's current health:**

| Dep | Health | Note |
|---|---|---|
| Frigate `<cam>_person_count` (post `_2`-migration) | HEALTHY (v5.78.0-era `_has_any_suffix_stripped`) | Not touched here. |
| `_apply_hold_decay` self-refresh | **BROKEN** (probe §Q4: 210-min episode against 33-min ceiling). | D1 target. |
| Per-camera face lookup | **DEAD** (0 hits/7d, probe §Q3). | D2 target. |
| Per-person `frigate_*_last_camera` | **DEAD** (all `_2`; Oji doubly wrong). | D2 target. |
| BLE `_ble_home_by_area` | Working; area-set disjoint from cameras. | NOT scoped (probe rejected code dedup repair). |

### 3.2 CONSUMER + call-site check

Reused from `PLANNING_guest_census_correctness.md` rev-2 §CONSUMER,
independently spot-verified at each cited line:

| Consumer | Site | Trust or Display | Affected by D1? | By D2? |
|---|---|---|---|---|
| Nobody-home → AWAY | `presence.py:1059-1063` | Trust | YES (decays faster) | YES (identified fixes) |
| `has_people` | `presence.py:1211-1214` | Trust | YES | YES |
| GUEST entry Path A (post v5.79.0: corroborator only) | `presence.py:4886` | Trust (weakened) | YES | YES |
| GUEST exit `unidentified_count == 0` | `presence.py:1243` | Trust | **YES — this is the exit that couldn't fire under the old decay tail; D1 makes it reachable.** | YES |
| Security lockdown | `security.py:774-969` | Trust | YES | YES |
| Phone-left-behind suppression | `binary_sensor.py:1769-1773` | Trust | YES | YES |
| Wake backstop | `presence.py:6004-6014` | Trust | YES | Indirect |
| Anomaly / optimizer suppression | `optimization.py:2610-2650`, `binary_sensor.py:2662-2669` | Trust | YES | YES |
| Sensor attrs (`persons_in_house`, `identified_persons_in_house`, `unidentified_persons_in_house`) | `sensor.py:3411-3612` | Display | YES | YES |

**Direction of change under D1+D2:** all trust consumers see a NUMERICALLY
SMALLER, FRESHER count more often. No consumer becomes newly permissive
in a dangerous direction: security uses `count > 0` (still fires on real
detection), phone-left-behind uses `count > 0` (unchanged sign), GUEST
exit becomes reachable (this is a KNOWN good — it is the residual gap the
v5.79.0 cycle explicitly left open, see `RESEARCH_...separation.md` §4.2
and shipped README).

**Explicit non-change (v5.79.0 preservation):** GUEST *entry* logic is
untouched. Path B (guest-room-led) remains the sole decider; Path A
(census) remains corroborator-only with the 0.9→0.95 shape shipped in
v5.79.0. D1 makes Path A's corroboration more truthful; it does not
re-promote it to decider.

---

## 4. Deliverables

### D1 — DECAY SEPARATION (core)

**Goal.** Give `_apply_hold_decay("house", …)` freshness-appropriate
semantics: (a) delete the linear `−1 per 300 s` slope by adopting the
already-running property-zone instant-drop; (b) kill the peak self-refresh
on `fresh == peak` so a systematically-wrong peak decays instead of
immortalising itself; (c) publish `peak_held` / `peak_age_seconds` /
`count_as_of` / `peak_refresh_count` (new diagnostic) on
`SIGNAL_CENSUS_UPDATED` so a held count is distinguishable from a fresh
one downstream.

**Files.**

- MODIFY `camera_census.py:2601-2605` — remove the `_store_peak(zone, fresh_count, now)`
  call on the `fresh_count == peak` branch. The stored peak/ts remain
  untouched; the count returned is still `fresh_count`. Add
  `_peak_refresh_suppressed_count` increment for observability.
- MODIFY `camera_census.py:2621-2632` — delete the house-zone linear
  decay body; fall through to the property-branch semantics (or refactor
  the branch to `if zone in ("house", "property"):` and drop the else).
  Byte-identical to the property branch's instant-drop reset.
- MODIFY `camera_census.py:1195-1210` — extend
  `SIGNAL_CENSUS_UPDATED` payload with `peak_held`,
  `peak_age_seconds`, `count_as_of` (ISO), and `peak_refresh_suppressed_count`.
  Additive; no key renames. All existing consumers ignore unknown keys
  (verify at build with a grep of `_handle_census_update`).
- MODIFY `sensor.py:3496-3497, 3647-3648` — add `count_as_of` and
  `peak_refresh_suppressed_count` to the published attr dict for
  `persons_in_house` (already publishes `peak_held` /
  `peak_age_minutes`). Convert minutes→seconds where appropriate for
  discrimination at short windows.

**Post-deploy config change (rung 2, no code):** reduce
`CONF_CENSUS_HOLD_INTERIOR` from 3 min → 1 min via the existing options
flow (`const.py:2679`). This is a discrete step after D1's code lands and
its live-validation completes.

**Knobs (see §5 knob table for rungs):**

- `CENSUS_PEAK_SUSTAIN_SECONDS` (existing, `const.py:2705`, 15 s) — rung 1
  UNCHANGED. Genuine measurement-quality gate; the operator does not
  legitimately re-tune this at runtime.
- `CENSUS_DECAY_STEP_SECONDS` (existing, `const.py:2697`, 300 s) — **rung 1
  DEAD** after D1. Retire the constant (or leave with a tombstone
  comment; builder's call — cheaper is to leave the constant and grep-verify
  zero consumers, matches v5.66.0 dead-const treatment).
- `CONF_CENSUS_HOLD_INTERIOR` (existing, rung 2) — UNCHANGED at code
  level; post-deploy operator tune 3 → 1 min.

**Acceptance criteria.**

- **Verify:** `_apply_hold_decay` has no `_store_peak` on the
  `fresh == peak` branch. Mutation-drill: re-add the call, one test
  (`test_d1_no_peak_self_refresh_under_steady_fresh`) goes red — the
  test asserts `peak_ts` unchanged across 10 ticks of steady fresh.
- **Verify:** the house-zone decay branch is a single-line instant-drop
  reset (byte-equivalent to the property branch at `:2633-2637`).
  Mutation-drill: re-introduce a `decay_steps` calc; one test
  (`test_d1_house_zone_instant_drop_after_hold`) goes red.
- **Sensor:** `sensor.universal_room_automation_persons_in_house` attrs
  include `peak_held`, `peak_age_minutes`, `count_as_of`,
  `peak_refresh_suppressed_count`.
- **Test:** `test_d1_payload_carries_freshness_stamps` — subscribe to
  `SIGNAL_CENSUS_UPDATED`, assert all four keys present and
  well-typed.
- **Test:** `test_d1_empty_house_reaches_zero_within_hold_plus_tick` —
  seed one interior fresh detection, then no detections for
  `hold + SCAN_INTERVAL_CENSUS + 5s`; assert `unidentified_count == 0`.
- **Live (discriminating):** with all four residents currently away
  (empty-house window per operator note, residents away until Wed PM),
  observe `persons_in_house` in the recorder for the first 60 min post-
  deploy: (a) reaches 0 within `hold + 30 s` after the last camera
  clears; (b) stays 0 (no rise on subsequent ticks unless a camera
  fires); (c) `peak_refresh_suppressed_count` is > 0 iff the pre-deploy
  self-refresh was firing on a systematic-error tail (it was). Contrast
  with the plausible-defect: if the value stays > 0 for > 5 min after
  the empty-house condition is reached, D1 has NOT fixed the tail. If
  it drops to 0 but climbs back within one tick, the peak-refresh
  deletion has an off-by-one path we missed.
- **Live (safety check):** GUEST exit becomes reachable. If the house
  is not in GUEST at deploy time (probable, given empty-house), record
  the first post-return `unidentified_count > 0` episode: peak decays
  to 0 within `hold + 1 tick` of the last camera clearing, not the
  pre-deploy 33-min minimum.

### D2 — `_2`-SUFFIX FRESH-FACE FIX (core)

**Goal.** Resolve `*_last_recognized_face` and `frigate_*_last_camera`
via the entity registry rather than by string construction. Reviving
face-based dedup is a direct census fix AND (per operator direction) a
shared prerequisite of `EXTERIOR-DWELL-LOITER-1`.

**Files.**

- MODIFY `camera_census.py:2385, 2399, 2432, 2752` — replace
  `face_sensor_id = f"sensor.{base_name}_last_recognized_face"` at all
  four sites with a registry lookup. Pattern (mirrors
  `presence.py:5354-5390`):
  ```python
  from homeassistant.helpers import entity_registry as er
  ent_reg = er.async_get(self.hass)
  # Try canonical unique_id; the Frigate integration keys face sensors
  # by "<device_id>_last_recognized_face" (verify at build).
  face_entity_id = ent_reg.async_get_entity_id(
      "sensor", "frigate", f"{camera_info.device_unique_id}_last_recognized_face"
  )
  ```
  Extract into a single helper `_resolve_face_entity_id(camera_info)` to
  avoid four copies.
- MODIFY `camera_census.py:3059` — same pattern for
  `sensor.frigate_<slug>_last_camera`.
- ADD `_face_lookup_missing_count` (int, per-tick reset) surfaced on
  the payload so we can measure post-deploy how often the CLOSED fail
  path was taken. **Critical:** on registry miss the code returns "no
  fresh face", NOT the pre-fix behaviour of "no credit" via a None
  state — those two happen to coincide today but the intent must be
  fail-CLOSED (no free `-1`).

**Verification approach — MANDATORY registry probe at build time.**
Before the builder edits code, run a one-shot registry read against the
live mount (`/Users/okosisi/ha-config/.storage/core.entity_registry`) to
confirm the unique_id convention Frigate uses for both entities. The
plan hypothesises `"<device>_last_recognized_face"` and
`"<slug>_last_camera"` but this MUST be verified against the live
registry, not fabricated. If the convention differs, the pattern is the
same (registry lookup); only the key changes.

**Knobs.** None. Behavioural fix; no new tunables. Fail-CLOSED policy
is a code-level invariant, not an operator knob.

**Acceptance criteria.**

- **Verify:** grep `camera_census.py` for
  `f"sensor.{...}_last_recognized_face"` and
  `f"sensor.frigate_{...}_last_camera"` — zero hits post-fix.
- **Sensor:** `persons_in_house` attrs include
  `face_recognized_persons` non-empty within 30 min post-deploy of any
  Frigate face event (`sensor.frigate_ezinne_last_camera_2` etc. going
  to a real camera name). Contrast: if it stays `[]` for > 30 min while
  the `_2` sensors are updating, the registry lookup is wrong.
- **Sensor:** `persons_in_house` attrs include
  `face_lookup_missing_count == 0` when all four persons' face sensors
  are registered. If > 0 at steady state, the unique_id convention is
  wrong.
- **Test:** `test_d2_resolves_last_recognized_face_via_registry` —
  fixture registers a Frigate face sensor with `_2` suffix; assert the
  cycle picks it up. Drill: unregister → test asserts `face_lookup_missing`
  increments and no `-1` credit is granted.
- **Test:** `test_d2_resolves_last_camera_by_person_slug` — same shape.
- **Test:** `test_d2_fails_closed_on_missing_registry_entry` — assert
  NO free `-1` credit is granted when the face sensor is absent.
- **Live (discriminating):** within the first face event post-return
  of any resident (Wed PM+), `identified_count` includes that person via
  the face route (not just BLE) — cross-check with the `_2` sensor's
  `last_changed` in the recorder. Contrast: if `identified_count` still
  tracks BLE-only, the face route is unreached.
- **Cross-cycle note.** Same fix unblocks `EXTERIOR-DWELL-LOITER-1`;
  document the shared dep in that card's `depends-on` field at build
  time.

### D3 — EXTERIOR DASHBOARD WIRING (bonus, small)

**Goal.** Per `AUDIT_exterior_census_supersession.md` KEEP-BOTH ruling:
do NOT overwrite `sensor.universal_room_automation_persons_on_property_exterior`.
Make the dashboard headline the linker's already-live
`sensor.ura_security_coordinator_outside_people_being_tracked` /
`sensor.exterior_person_tracks_active` with the naive sum as a degraded
fallback (guard G1: never show 0 when linker inactive) + a divergence
indicator.

**Scope discipline.** Dashboard-only. **NO** URA-side code change to
any census producer, sensor, or dispatch payload. No change to
`camera_census.py:1502-1580`. All work lives in the PWA repo
(`~/Code/ura-dashboard-pwa`) — likely a Presence card component
change.

**Files.**

- PWA: `~/Code/ura-dashboard-pwa/src/…` (Presence card, exact file
  determined at build) — swap the "on property" headline source from
  `sensor.universal_room_automation_persons_on_property_exterior` to
  `sensor.exterior_person_tracks_active` (or the `_outside_people_...`
  slug — verify at build via `ha_get_state`).
- PWA: add G1 fallback logic — if the linker sensor is `unavailable`
  OR its parent `switch.ura_security_coordinator_exterior_path_tracking`
  is off, fall back to the naive sensor value; annotate the card as
  "degraded".
- PWA: add divergence indicator — when
  `linker_value != naive_value`, show both (e.g. "tracks=1 · raw=3").
- URA repo: **NO changes.**

**Knobs.** None.

**Acceptance criteria.**

- **Verify:** URA-side `git diff` for D3 is empty.
- **Live (dashboard):** with linker active and naive == linker (probe
  baseline case), headline shows the linker value; no divergence badge.
- **Live (discriminating):** simulate G1 by turning
  `switch.ura_security_coordinator_exterior_path_tracking` off — card
  shows the naive value AND a "degraded" annotation (NOT 0 while the
  naive is > 0). Contrast: if the card shows 0, G1 is not wired.
- **Live (discriminating):** when a real 1-walker-across-3-cameras
  event occurs (opportunistic post-deploy), the headline reads 1 (via
  linker) AND the divergence badge shows `raw=3`. If both read 3, the
  headline source is still naive.

---

## 5. Numbers-get-knobs table

| Number | Rung | Home | Why (one line) |
|---|---|---|---|
| `CENSUS_PEAK_SUSTAIN_SECONDS = 15 s` | 1 | `const.py:2705` | Measurement-quality gate; changing it warrants review. UNCHANGED. |
| `CENSUS_DECAY_STEP_SECONDS = 300 s` | 1 (retired) | `const.py:2697` | Dead after D1. Leave with tombstone comment. |
| `CONF_CENSUS_HOLD_INTERIOR` | 2 | options flow | Per-deployment freshness/robustness trade; operator legitimately tunes after observing detector cadence. Post-deploy 3 → 1 min. |
| `CENSUS_FACE_RECOGNITION_WINDOW_SECONDS = 1800 s` | 1 today; should promote to 2 (out of scope) | `const.py:2711` | Noted in research §5 change #12 — deferred. |
| `_face_lookup_missing_count` (D2) | n/a (diagnostic, per-tick) | payload attr | Not a knob; a counter. |
| `_peak_refresh_suppressed_count` (D1) | n/a (diagnostic) | payload attr | Not a knob; a counter. |
| Dashboard divergence threshold | n/a (D3, display-only) | PWA | Not a URA knob. |

**Kill-switch semantics.** No new kill switches. D1's mechanism is
delete-only (no way to "turn the slope back on"); if a regression
appears, the rollback is the deploy-level version pin. D2's
registry-resolve has no kill switch — the failing-closed path IS the
degraded mode.

---

## 6. Non-goals (explicit)

- **GUEST policy.** All guest entry/exit changes shipped in v5.79.0
  (Paths B/D3 lead; INV-GUEST-LEAD). This cycle does NOT touch
  `presence.py:1241-1274`, `presence.py:4830-4938`, or
  `presence.py:5382-5404`. D1's decay change makes the v5.79.0 GUEST
  exit *reachable* on realistic timescales, which is a KNOWN good
  documented in v5.79.0 README's "residual" section.
- **Code dedup / BLE-cancel repair.** Probe measured 0 s / 7 d benefit;
  the real gap is OPERATOR CONFIG (3 of 7 camera areas have no URA
  room; residents in a camera-covered room only 3.75% of person-min).
  This cycle does NOT touch `_ble_home_by_area`
  (`camera_census.py:2285`), `_get_ble_persons` (`:1951`), or the
  Step-3 subtraction (`:2820-2860`).
- **Exterior census producer swap.** KEEP BOTH ruling; the naive
  `_calculate_property_census` (`camera_census.py:1502-1580`) stays.
- **`CensusHoldDecayService` extraction.** Explicitly deferred; deleting
  the bad branch in place is cheaper and lower-risk than extracting a
  service (v4.7.18 D1 scope was ~120 LoC + tests; this cycle's D1 is
  ~15 LoC + attrs). Park the service extraction under a follow-up card
  with the trigger: "if a second consumer other than presence needs
  `peek()` access."
- **`identified_count > 4 with 4 tracked persons` (271 min/7 d,
  probe §Q4).** Cannot be diagnosed from recorder — track separately as
  a new inbox card at build time; NOT in this cycle.
- **`CENSUS_FACE_RECOGNITION_WINDOW_SECONDS` rung promotion** (research
  §5 change #12). Small config-flow addition; defer to keep this cycle
  focused.

---

## 7. Marginal-benefit decomposition

Per `feedback_marginal_benefit_pushback.md`, decompose before elaborating.

| Deliverable | Simplest version | Marginal benefit | Marginal risk | Verdict |
|---|---|---|---|---|
| **D1 decay** | Delete the two offending branches (peak self-refresh + linear slope). Reuse the already-live property-zone instant-drop. | Captures the measured 74.5% (12.83 h / 7 d) of elevated-census time. Makes v5.79.0 GUEST exit reachable in realistic time (33 min → ≤ 4 min today, ≤ 2 min after Number tune). | Small. Delete-only. State machine already runs this branch for the property zone. Empty-house window (residents away) is an ideal decay test. Payload extension is additive. | **GO.** Clear marginal benefit; risk is bounded and testable. |
| **D2 registry fix** | Registry lookup at 5 sites via one helper. Precedent already in v5.79.0 D3. | Revives a defence that has fired 0×/7 d. Prerequisite for any face-based dedup ever working AND for `EXTERIOR-DWELL-LOITER-1`. | Small. New code is a well-tested pattern. Fail-CLOSED policy is safer than today's silent no-op. Frigate unique_id convention must be verified at build (probe), not fabricated. | **GO.** Cross-cycle unblock alone justifies it. |
| **D3 dashboard** | PWA-only source swap + G1 fallback + divergence badge. | Surfaces the correct 1-walker-reads-1 headline; keeps the naive as a conservative floor per KEEP-BOTH. | Effectively zero (no URA-side change). | **GO (bonus).** Cheap; delivers the operator's exterior-count instinct without any producer surgery. |

**No deliverable is dropped.** No fancier alternatives were considered
worth speccing — D1's alternative (extract `CensusHoldDecayService`) was
explicitly parked as a v4.7.18 follow-up with a documented evidence
trigger. Recorded here rather than elaborated.

---

## 8. Plan Completion Tracking (mandatory)

Post-implementation, account for each of:

- D1 code changes (branches removed, payload extended, sensor attrs
  extended) — complete / partial + reason.
- D1 post-deploy operator config tune (3 → 1 min) — done / pending
  (this is a discrete step AFTER live-validation, not part of the
  deploy).
- D2 registry-resolve at all 5 sites — complete / partial + reason.
- D2 build-time registry probe outcome — the unique_id convention
  actually used by Frigate (recorded in the build's fix-up doc or
  README).
- D3 PWA changes — deployed / pending (the PWA repo has its own
  deploy cadence; note where the change lives).
- Any deferrals: `identified_count > 4` diagnostic (new card),
  `CensusHoldDecayService` extraction (follow-up trigger),
  `CENSUS_FACE_RECOGNITION_WINDOW_SECONDS` rung promotion.

---

## 9. Recall

- "Census accuracy cycle"
- "Census decay separation"
- "Fresh-face registry fix"
- "Exterior dashboard KEEP BOTH"
