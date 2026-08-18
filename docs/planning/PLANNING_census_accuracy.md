# PLANNING — Census Accuracy (interior)

**Rev:** rev-2 (2026-08-17)
**Card:** `CENSUS-ACCURACY-1` (Kanban 2026-08-17)
**Scope:** INTERIOR census accuracy. Two core deliverables + one
exterior-dashboard bonus (rev-2: now spans HA URA v6 + URA v8 + PWA per
operator scope change — see §Changelog and D3). Not guest policy
(shipped v5.79.0). Not code dedup repair (probe rejected). Not exterior
census producer swap (KEEP BOTH ruling).
**Probe already run:** `docs/planning/AUDIT_census_accuracy_probe.md`
(commit 4f67edfea) — measurement-first gate; results wired into the
Go/No-Go per deliverable below.
**Adjudication read:** `docs/planning/AUDIT_exterior_census_supersession.md`
(commit eb2caa3c8) — KEEP BOTH.
**Plan review of record:** `docs/reviews/code-review/census_accuracy_plan_review.md`
(commit 155053bf0) — verdict PLAN-NEEDS-FIXES; rev-2 resolves all HIGH/MEDIUM.

---

## Changelog

### rev-2 (2026-08-17) — plan-review fixes + D3 scope change

> **D3 FOLD CONFIRMED (operator 2026-08-17 "Fold it in and go"):** D3 (exterior deduped-headline + naive-fallback + divergence) ships IN cycle 2 across HA URA v6 + URA v8 + PWA. Split option declined. D3 wires AFTER D1/D2 land (it consumes D1's new peak_held/peak_age/count_as_of/divergence attributes) and touches NO census-producer code, so it rides the same cycle without expanding the Tier 2-DB producer review.

- **F1 (HIGH) resolved.** D2 approach rewritten. The prior snippet
  (`ent_reg.async_get_entity_id("sensor", "frigate", f"{camera_info.device_unique_id}_last_recognized_face")`)
  was fabrication — the live Frigate unique_id format is
  `<Frigate-ULID>:sensor_recognized_face:<CamObjName>` (mixed-case camera
  object name, e.g. `01KM239Z8ZQWQTN1D9CV5JRA7V:sensor_recognized_face:ArmCrestASH41B`),
  not derivable from `camera_info`. The v5.79.0 D3 precedent works only
  because URA *defines* its own unique_ids; Frigate is external. Rev-2
  drops the unique_id path; face resolution uses `hass.states.get`
  against both the un-suffixed and `_2`-suffixed entity_id variants
  (mirrors the shipped v5.78.0 `_has_any_suffix_stripped` /
  `_strip_disambiguation_suffix` pattern in
  `camera_resolver.py:317-327`). `last_camera` resolution uses a
  build-time registry enumeration of `sensor.frigate_*_last_camera*`
  matched to persons — the person→frigate-first-name mapping is NOT
  constructed from the configured URA person name (verified: URA
  configures `oji_udezue`; live entity is `sensor.frigate_oji_last_camera_2`).
- **F2 (MEDIUM) resolved.** Site count corrected 5 → 4. Line 2385 is a
  docstring, not a construction site. Real sites: `:2399, :2432, :2752`
  (face) + `:3059` (last_camera).
- **F3 (MEDIUM) resolved.** D1 empty-house acceptance criterion now
  includes an interior-only precondition guard
  (`sum(interior Frigate _person_count) == 0` for `hold + 1 tick`) and
  a positive discriminator (`peak_refresh_suppressed_count > 0` proves
  the deleted code path actually ran, not that the count happened to
  be 0). Prevents outdoor Frigate wildlife/wind/delivery firings from
  spoofing the acceptance test.
- **F4 (LOW) resolved.** D1 "Live (safety check)" now requires
  cross-checking any post-deploy census-driven AWAY transition against
  BLE person absence AND `person_coordinator` tracking_status; a wrong
  AWAY (from an unrelated presence-layer regression) is now detectable
  rather than silently attributed to the decay change.
- **F5 (LOW) resolved.** INV-DECAY-HONEST reworded to reference
  measurable preconditions (interior person_count sum, SCAN_INTERVAL_CENSUS,
  the new `peak_refresh_suppressed_count` counter) rather than
  colloquial "live camera / asserted a body".
- **Operator scope change on D3 (2026-08-17).** D3 targets HA Lovelace
  dashboards **URA v6 AND URA v8** in addition to the PWA. Dashboard
  edits go through `ha_config_set_dashboard`, EXTENDING existing
  dashboards (per home-assistant best-practices skill), not replacing.
  Producer stays unchanged (KEEP BOTH ruling). D3 re-scope assessment
  and split recommendation captured in §D3 and §7.
- **Non-blocking review observations folded in.**
  `count_as_of` = `dt_util.utcnow().isoformat()` at DISPATCH time (not
  compute-start). Diagnostic-counter lifecycles clarified:
  `peak_refresh_suppressed_count` LIFETIME (monotonic since coordinator
  start; matches "was systematic-error tail firing"),
  `_face_lookup_missing_count` PER-TICK (matches "is this tick's lookup
  healthy").

### rev-1 (2026-08-17) — initial plan (commit 89af06222)

---

## 0. Institutional Context Verified

### 0.1 Prior planning docs / research consulted (full read)

| Doc | Relevance |
|---|---|
| `docs/planning/RESEARCH_census_vs_guest_separation.md` | Authoritative separation-of-concerns synthesis. §2 = the decay ruling. §2.5 documents that `CensusHoldDecayService` (v4.7.18 D1) and `peek()` (D5) were designed and NEVER BUILT. §5 change #5 = "delete the linear decay slope on the house zone; adopt the property zone's instant-drop". |
| `docs/planning/PLANNING_v4.7.18_census_service_shared_refactor.md` | D1 (`CensusHoldDecayService`) + D5 (`peek()`) planned, not shipped. This cycle DELIBERATELY does NOT extract a service — see §6 non-goals; we edit in place at `camera_census.py:2516-2637`. |
| `docs/planning/AUDIT_census_accuracy_probe.md` | 74.5%/12.83h of elevated time = pure decay tail. Fresh-face fired 0x/7d. Dedup repair buys ~0 (area-set disjoint). |
| `docs/planning/AUDIT_exterior_census_supersession.md` | KEEP BOTH: `persons_on_property_exterior` (naive) NOT overwritten. Dashboard headlines the linker's already-live `exterior_person_tracks_active` with G1 fallback. |
| `docs/planning/PLANNING_guest_census_correctness.md` (rev-2, shipped v5.79.0) | Review B has the consumer enumeration for `unidentified_count` / `identified_count` — REUSED here rather than re-enumerated. |
| `docs/planning/AUDIT_census_accuracy_regression.md` | `_2`-suffix migration audit; source of `_has_any_suffix_stripped` precedent (`camera_resolver.py:317-327`) — now the primary D2 pattern in rev-2. |

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
  `:2399`, `:2432`, `:2752` (three face construction sites) + `:3059`
  (last_camera construction site) — **4 sites total** (rev-2 correction;
  `:2385` is a docstring, not a site).
- `custom_components/universal_room_automation/camera_resolver.py:284-332`
  (`_strip_disambiguation_suffix`, `_has_any_suffix_stripped`,
  `_prefer_canonical`) — the shipped v5.78.0 pattern D2 rev-2 mirrors.
- `custom_components/universal_room_automation/sensor.py:3411-3530`
  (`_CensusBaseSensor` + `persons_in_house` attrs, already publishes
  `peak_held` / `peak_age_minutes`); `:3615-3649`
  (`URAPersonsOnPropertySensor`, naive exterior, KEEP); `:3849-3928`
  (`exterior_person_tracks_active` + linker-fed sensors, KEEP as
  headline source for the D3 dashboard change).
- `custom_components/universal_room_automation/domain_coordinators/presence.py:4323`
  (`_handle_census_update`), `:5354-5390` (v5.79.0 D3 precedent for
  URA-defined-unique_id registry lookup — NOT directly applicable to
  Frigate; see rev-2 D2 approach change).
- **Live registry verified** (rev-2, plan review §3): 23 Frigate face
  sensors (all `_2`-suffixed, unique_id format
  `<Frigate-ULID>:sensor_recognized_face:<CamObjName>`) + 5
  `frigate_*_last_camera` entities (`Oji`/`Ezinne`/`Jaya`/`Ziri` + a
  `Default`, all with `_2` suffix, unique_id
  `<Frigate-ULID>:sensor_global_face:<PersonName>`).

### 0.4 REUSED / NEW per proposed addition

| Proposed | Verdict | Justification |
|---|---|---|
| Instant-drop after hold on the house zone | **REUSED** | Branch already written and running for property zone at `camera_census.py:2633-2637`. We delete `:2621-2632` (the linear slope) and reuse the property branch symmetrically. |
| Kill the peak self-refresh on `fresh == peak` | **REUSED (delete-only)** | The refresh site is a single call at `camera_census.py:2601-2605`. No new mechanism. |
| `peak_held` / `peak_age_seconds` / `count_as_of` on the dispatch payload | **PARTIAL REUSE** | `peak_held` + `peak_age_minutes` are already returned by `_apply_hold_decay` (`:2521`) and already published on the sensor attrs (`sensor.py:3496-3497, 3647-3648`). NEW: add them to the `SIGNAL_CENSUS_UPDATED` payload (`camera_census.py:1195-1210`) + a `count_as_of` ISO timestamp (stamped at DISPATCH time, `dt_util.utcnow().isoformat()`) so consumers can distinguish held-vs-fresh without re-reading the sensor. |
| `peak_refresh_suppressed_count` diagnostic attr (LIFETIME) | **NEW** | Probe §Q4 CONFIDENCE explicitly asks for this to make self-refresh directly measurable, AND it is the positive discriminator for D1's empty-house acceptance test (rev-2 F3 fix). Adds ~3 LoC on the state machine + one attr. |
| Registry / states lookup for face + last_camera (rev-2) | **REUSED pattern** | Mirrors shipped v5.78.0 `_has_any_suffix_stripped` at `camera_resolver.py:317-327`. NEW code = ~40 LoC across 4 sites via two small helpers. See D2. |
| `CONF_CENSUS_HOLD_INTERIOR` change 3 → 1 min | **REUSED (config only)** | Already a rung-2 config key at `const.py:2679`. Post-deploy Number/options change, not a code change. |
| Exterior dashboard swap (PWA + HA URA v6 + HA URA v8) | **Dashboard-only** | `exterior_person_tracks_active` (`sensor.py:3849`) already live. No URA-side code change. HA-side: `ha_config_set_dashboard` extend calls per home-assistant best-practices skill. |

### 0.5 Memory bodies pulled

- `feedback_measure_before_build.md` — probe is done; this plan is gated on it.
- `feedback_hollow_test_anchors.md` — every test below drills by DETACHING
  the value, not by grepping the source.
- `feedback_suppression_needs_discharge.md` — deleting the peak-refresh is
  a suppression; the discharge is the natural downward path (fresh < peak →
  hold expiry → instant drop). Restart resets peak (in-memory), which is
  the acceptable backstop.
- `feedback_no_fabrication.md` — every line above cites file:line, and
  rev-2 F1 fix is the direct application of this rule (the rev-1 D2
  snippet was exactly the class this rule catches).

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
- **B — Face/last_camera resolution integrity + cross-consumer payload
  shape.** Both entity_id variants tried (un-suffixed + `_2`) at all 4
  sites; behavior when neither variant resolves (must fail-CLOSED = no
  free `-1` credit); build-time enumeration of
  `sensor.frigate_*_last_camera*` matched to persons is correct given
  the URA-configured person names (`oji_udezue` vs frigate `Oji`);
  payload shape change on `SIGNAL_CENSUS_UPDATED` — every consumer at
  `_handle_census_update` sites still reads what it expects, additive
  only.
- **C — Test authority + observability.** Every anchor drills by DETACHING
  the value (delete `peak_held` from payload → does a specific test go red?
  neuter the face resolver → does a specific test go red? mutate the
  hold-expiry branch → does a specific test go red?). No monkeypatch-only
  proofs. Live-validation criteria must DISCRIMINATE the fix from a
  plausible OTHER failure (e.g. "count went to 0" is not enough — it must
  go to 0 within the empty-house-plus-1-detector-cadence window AND not
  climb back on the next tick AND `peak_refresh_suppressed_count > 0`
  during any interval where the pre-deploy tail would have fired).

**No operator elevation to Tier 3** — the falsifiable invariant is
tightly bounded (one state machine, one number), no state-machine ×
time-seam ingredient, no cross-coordinator ripple beyond a payload
additive extension.

---

## 2. Falsifiable Invariants (up front)

Each invariant is stated in a form a plausible DEFECT would violate. The
v5.79.0 lesson (INV-GUEST-LEAD was satisfied by a real defect) is the
reason each one is paired with a discriminating live observation.

- **INV-DECAY-HONEST (rev-2 reworded).** *For every census tick where
  `sum(<interior Frigate>._person_count) == 0` continuously for the
  preceding `hold + SCAN_INTERVAL_CENSUS`,
  `persons_in_house.unidentified_count == 0` AND `peak_held == False`.
  Additionally, over any 7-day window containing an episode that
  pre-deploy would have exhibited the self-refresh tail,
  `peak_refresh_suppressed_count` MUST have incremented (proves the
  deleted code path is on the wire, not merely absent from observation).*
  Violated by: any decay slope, any peak self-refresh, any held tail
  longer than `hold + 1 tick`, or a wiring miss that leaves the counter
  at 0 during known-elevated intervals.
- **INV-PEAK-NO-SELF-REFRESH.** *For every census tick, `peak_ts` is
  only ever written on a strict upward promotion (pending → peak) or on
  a downward reset-to-fresh at hold-expiry. `fresh == peak` MUST NOT
  refresh `peak_ts`.* Directly falsifiable by drilling
  `_apply_hold_decay` with a steady fresh sequence and asserting
  `peak_ts` is unchanged after N ticks.
- **INV-FRESH-FACE-RESOLVES (rev-2 reworded).** *For every configured
  Frigate person camera whose face sensor exists in `hass.states` under
  either the un-suffixed OR `_2`-suffixed entity_id, the census
  resolves it via `hass.states.get` on both variants (canonical
  preferred, `_2` fallback). If neither variant resolves, the code
  fails CLOSED (no `-1` credit) and increments
  `_face_lookup_missing_count` for the current tick.* Falsifiable by
  registering only the `_2` variant and asserting the shipped resolver
  returns that entity_id (drill: unregister both → assert counter
  increments and no free `-1` credit).
- **INV-PAYLOAD-DISCRIMINABLE.** *Every `SIGNAL_CENSUS_UPDATED` payload
  carries `peak_held`, `peak_age_seconds`, `count_as_of` (ISO,
  DISPATCH-time), `peak_refresh_suppressed_count` (LIFETIME), and
  `face_lookup_missing_count` (PER-TICK).* A consumer reading the
  payload can always tell whether the count is an observation or an
  echo, and whether this tick's face path was healthy.

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
     the constructed `sensor.<base>_last_recognized_face` doesn't exist
     under that name; the live sensors are `_2`-suffixed — probe Q3).
  2. `held_unidentified = _apply_hold_decay(raw, "house", now)`
     (`:2516-2637` — the state machine that self-refreshes on
     `fresh == peak` at `:2601-2605`; this is the 74.5% cost).
  3. `identified_count = len(ble_persons ∪ face_recognized)` where
     `face_recognized = _get_face_recognized_person_names` (`:3031-3110`,
     constructs `sensor.frigate_<slug>_last_camera` — **also
     mismatches live registry**: (a) URA slug `oji_udezue` vs frigate
     first-name-lowercase `oji`; (b) `_2` suffix on all 4 person
     entities; every value in the union comes from BLE today).
  4. `total = identified_count + held_unidentified`.

**Each dependency's current health:**

| Dep | Health | Note |
|---|---|---|
| Frigate `<cam>_person_count` (post `_2`-migration) | HEALTHY (v5.78.0-era `_has_any_suffix_stripped`) | Not touched here. |
| `_apply_hold_decay` self-refresh | **BROKEN** (probe §Q4: 210-min episode against 33-min ceiling). | D1 target. |
| Per-camera face lookup | **DEAD** (0 hits/7d, probe §Q3). | D2 target. |
| Per-person `frigate_*_last_camera` | **DEAD** (all `_2`; slug axis also wrong: URA `oji_udezue` ≠ frigate `oji`). | D2 target. |
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
v5.79.0. D1 makes Path A **stricter** (smaller/fresher count → harder to
corroborate a phantom guest); it does not re-promote it to decider.

**Nobody-home → AWAY becomes newer/faster (rev-2 F4 note).** Post-D1
that transition fires within `hold + 1 tick` instead of `hold + linear
slope`. Under a plausible different failure (stale mmWave in a room
while a resident sits silently), AWAY could fire while a person is
home — but that would be a presence-layer failure, not a census
failure. See D1 "Live (safety check)" for the discriminating audit.

---

## 4. Deliverables

### D1 — DECAY SEPARATION (core)

**Goal.** Give `_apply_hold_decay("house", …)` freshness-appropriate
semantics: (a) delete the linear `−1 per 300 s` slope by adopting the
already-running property-zone instant-drop; (b) kill the peak self-refresh
on `fresh == peak` so a systematically-wrong peak decays instead of
immortalising itself; (c) publish `peak_held` / `peak_age_seconds` /
`count_as_of` / `peak_refresh_suppressed_count` / `face_lookup_missing_count`
on `SIGNAL_CENSUS_UPDATED` so a held count is distinguishable from a
fresh one downstream.

**Files.**

- MODIFY `camera_census.py:2601-2605` — remove the `_store_peak(zone, fresh_count, now)`
  call on the `fresh_count == peak` branch. The stored peak/ts remain
  untouched; the count returned is still `fresh_count`. Add
  `_peak_refresh_suppressed_count` increment (LIFETIME, monotonic since
  coordinator start) for observability.
- MODIFY `camera_census.py:2621-2632` — delete the house-zone linear
  decay body; fall through to the property-branch semantics (or refactor
  the branch to `if zone in ("house", "property"):` and drop the else).
  Byte-identical to the property branch's instant-drop reset.
- MODIFY `camera_census.py:1195-1210` — extend
  `SIGNAL_CENSUS_UPDATED` payload with `peak_held`,
  `peak_age_seconds`, `count_as_of` (`dt_util.utcnow().isoformat()`
  stamped at DISPATCH time, NOT compute-start), `peak_refresh_suppressed_count`
  (LIFETIME), and `face_lookup_missing_count` (PER-TICK — reset each
  tick). Additive; no key renames. All existing consumers ignore
  unknown keys (verify at build with a grep of `_handle_census_update`).
- MODIFY `sensor.py:3496-3497, 3647-3648` — add `count_as_of`,
  `peak_refresh_suppressed_count`, and `face_lookup_missing_count` to
  the published attr dict for `persons_in_house` (already publishes
  `peak_held` / `peak_age_minutes`). Convert minutes→seconds where
  appropriate for discrimination at short windows.

**Post-deploy config change (rung 2, no code):** reduce
`CONF_CENSUS_HOLD_INTERIOR` from 3 min → 1 min via the existing options
flow (`const.py:2679`). This is a discrete step after D1's code lands and
its live-validation completes.

**Knobs (see §5 knob table for rungs):**

- `CENSUS_PEAK_SUSTAIN_SECONDS` (existing, `const.py:2705`, 15 s) — rung 1
  UNCHANGED. Genuine measurement-quality gate.
- `CENSUS_DECAY_STEP_SECONDS` (existing, `const.py:2697`, 300 s) — **rung 1
  DEAD** after D1. Leave with tombstone comment; grep-verify zero
  consumers post-fix.
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
  `peak_refresh_suppressed_count` (LIFETIME), `face_lookup_missing_count`
  (PER-TICK).
- **Test:** `test_d1_payload_carries_freshness_stamps` — subscribe to
  `SIGNAL_CENSUS_UPDATED`, assert all five keys present and
  well-typed; assert `count_as_of` is close to `dt_util.utcnow()` at
  dispatch (not compute-start).
- **Test:** `test_d1_empty_house_reaches_zero_within_hold_plus_tick` —
  seed one interior fresh detection, then no detections for
  `hold + SCAN_INTERVAL_CENSUS + 5s`; assert `unidentified_count == 0`.
- **Live (empty-house discriminating, rev-2 F3).** The empty-house
  observation is valid ONLY during intervals where
  `sum(<interior Frigate>._person_count) == 0` continuously for
  `hold + SCAN_INTERVAL_CENSUS`. Enumerate the interior camera list
  from `camera_manager.get_all_frigate_cameras()` at build time and
  record it in the README. Under a valid interval:
  (a) `persons_in_house` reaches 0 within `hold + 30 s` after the last
      camera clears;
  (b) stays 0 (no rise on subsequent ticks unless a camera fires);
  (c) **positive discriminator:** `peak_refresh_suppressed_count > 0`
      LIFETIME across any interval where a pre-D1 systematic-error tail
      would have fired (the probe's 74.5% elevated-time evidence says
      this WILL fire). If (c) is 0 while (a)+(b) look fine, the deleted
      code path is not wired — the "success" is coincidental.
  Contrast: outdoor Frigate firings on wildlife/wind/delivery do NOT
  invalidate the observation because the precondition guard is
  interior-only. Intervals containing any interior camera firing are
  recorded as "inconclusive" (not fail).
- **Live (safety check, rev-2 F4 audit).** GUEST exit becomes
  reachable. If the house is not in GUEST at deploy time (probable,
  given empty-house), record the first post-return `unidentified_count > 0`
  episode: peak decays to 0 within `hold + 1 tick` of the last camera
  clearing, not the pre-deploy 33-min minimum. AND: for the first
  census-driven AWAY transition post-deploy, cross-check BLE person
  absence AND `person_coordinator` tracking_status. If AWAY fires
  while any resident's BLE says home OR tracking_status ≠ AWAY, log
  an "AWAY-with-resident-present" audit event and note in the
  README write-back table. (Observability requirement, NOT a
  ship-gate — the point is that a wrong AWAY from an unrelated
  presence-layer regression is detectable, not silently attributed to
  the decay change.)

### D2 — `_2`-SUFFIX FRESH-FACE FIX (core, rev-2 rewritten)

**Goal.** Resolve `sensor.*_last_recognized_face` and
`sensor.frigate_*_last_camera` in a way that survives the `_2`
disambiguation suffix and does NOT fabricate Frigate's unique_id.
Reviving face-based dedup is a direct census fix AND (per operator
direction) a shared prerequisite of `EXTERIOR-DWELL-LOITER-1`.

**Approach (rev-2).** Two small helpers, both `hass.states.get`-based
(mirrors the shipped v5.78.0 `_has_any_suffix_stripped` pattern in
`camera_resolver.py:317-327`). NO Frigate unique_id construction — the
live format `<Frigate-ULID>:sensor_recognized_face:<CamObjName>` is
external and not derivable from URA state.

1. **`_resolve_face_entity_id(camera_info) -> str | None`.** For a
   camera whose base name is `<base>`, try in order:
   - `hass.states.get(f"sensor.{base}_last_recognized_face")`
   - `hass.states.get(f"sensor.{base}_last_recognized_face_2")`
   Return the entity_id of the first hit whose state is not
   `unavailable`/`unknown`. Return `None` if neither hits — caller
   fails CLOSED (no `-1` credit; increment
   `_face_lookup_missing_count` for the current tick).

2. **`_resolve_last_camera_entity_id(person)` via build-time
   enumeration.** Do NOT construct `sensor.frigate_{person_slug.lower()}_last_camera`
   — the axis is wrong on TWO counts: (a) the URA-configured slug
   (`oji_udezue`) is NOT the frigate first-name-lowercase (`oji`);
   (b) the `_2` suffix. Instead:
   - At coordinator setup (or on first use, memoised), ENUMERATE
     `entity_registry.async_entries_for_platform(er, "frigate")`
     filtered to entities whose `entity_id` matches
     `sensor.frigate_*_last_camera` OR `sensor.frigate_*_last_camera_2`.
     For each hit, read its `unique_id` — Frigate's format is
     `<ULID>:sensor_global_face:<PersonName>` where `<PersonName>` is
     the frigate face-library name in mixed case (`Oji`, `Ezinne`,
     `Jaya`, `Ziri`, `Default`). Extract `<PersonName>` and lowercase
     it as the mapping key.
   - Build a dict `frigate_person_key -> entity_id`.
   - Match URA persons to frigate keys by comparing
     `person.name.split()[0].lower()` (first-name lowercase) against
     the dict key. Record unmatched persons + unmatched frigate
     entries in a build-time log line for operator review; the
     enumeration is small (4 residents + Default).
   - Fail-CLOSED: if a URA person has no matching frigate entry,
     `_get_face_recognized_person_names` simply does not credit that
     person via the face path (BLE path unchanged).

**Files.**

- MODIFY `camera_census.py:2399, 2432, 2752` — replace each
  `face_sensor_id = f"sensor.{base_name}_last_recognized_face"` with a
  call to `self._resolve_face_entity_id(camera_info)`. (3 face sites,
  NOT `:2385` which is a docstring.)
- MODIFY `camera_census.py:3059` — replace
  `f"sensor.frigate_{person_slug.lower()}_last_camera"` with a
  dictionary lookup against the memoised
  `_frigate_person_last_camera_map` built by
  `_resolve_last_camera_entity_id`.
- ADD `_face_lookup_missing_count` (int, per-tick reset) surfaced on
  the payload via D1's payload extension so we can measure post-deploy
  how often the CLOSED fail path was taken. **Critical:** on missing
  resolution the code returns "no fresh face", NOT the pre-fix
  behaviour of "no credit" via a None state — those two happen to
  coincide today but the intent must be fail-CLOSED (no free `-1`).
- ADD both helpers on `PersonCensus` (or its shared base) — extract to
  avoid four copies and enable a single mutation target for tests.

**Verification approach — the registry probe already ran.**
Rev-2 F1 fix incorporates the plan-review §3 live probe results
directly (23 face sensors `_2`-suffixed; 5 `last_camera` entities;
person-name axis is frigate first-name capitalized, e.g. `Oji`, not the
URA configured `oji_udezue`). No further live probe is required at
build; the helpers are `hass.states.get`-based (probe-tolerant) and the
`last_camera` map is built from the live registry at coordinator setup.

**Knobs.** None. Behavioural fix; no new tunables. Fail-CLOSED policy
is a code-level invariant, not an operator knob.

**Acceptance criteria.**

- **Verify:** grep `camera_census.py` for
  `f"sensor.{...}_last_recognized_face"` and
  `f"sensor.frigate_{...}_last_camera"` — zero hits post-fix (except
  inside the two helpers).
- **Sensor:** `persons_in_house` attrs include
  `face_recognized_persons` non-empty within 30 min post-deploy of any
  Frigate face event (`sensor.frigate_ezinne_last_camera_2` etc.
  updating to a real camera name). Contrast: if it stays `[]` for
  > 30 min while the `_2` sensors are updating, the helper's mapping
  is wrong.
- **Sensor:** `persons_in_house` attrs include
  `face_lookup_missing_count == 0` at steady state when all four
  residents' face sensors resolve. If > 0 persistently, one of the
  base-name → sensor mappings is wrong.
- **Test:** `test_d2_resolves_last_recognized_face_via_states` —
  fixture registers a `_2`-suffixed state; assert the resolver
  returns the `_2` entity_id. Drill: remove the state → assert
  `face_lookup_missing_count` increments and no `-1` credit granted.
- **Test:** `test_d2_resolves_last_camera_via_registry_enumeration` —
  fixture registers frigate `last_camera` entities with unique_ids
  matching `<ULID>:sensor_global_face:<PersonName>` for two persons;
  assert the built map has both. Drill: register a `_2` variant only
  → assert the map still contains the entry.
- **Test:** `test_d2_fails_closed_on_missing_person_mapping` — URA
  person with no frigate match → assert no free `-1` credit and no
  crash.
- **Live (discriminating):** within the first face event post-return
  of any resident (Wed PM+), `identified_count` includes that person
  via the face route (not just BLE) — cross-check with the `_2`
  sensor's `last_changed` in the recorder. Contrast: if
  `identified_count` still tracks BLE-only, the face route is
  unreached.
- **Cross-cycle note.** Same fix unblocks `EXTERIOR-DWELL-LOITER-1`;
  document the shared dep in that card's `depends-on` field at build
  time.

### D3 — EXTERIOR DASHBOARD WIRING (bonus, rev-2 re-scoped)

**Goal.** Per `AUDIT_exterior_census_supersession.md` KEEP-BOTH ruling:
do NOT overwrite `sensor.universal_room_automation_persons_on_property_exterior`.
Make the exterior "on property" headline in each surface show the
linker's already-live
`sensor.ura_security_coordinator_outside_people_being_tracked` /
`sensor.exterior_person_tracks_active` with the naive sum as a degraded
fallback (guard G1: never show 0 when linker inactive) + a divergence
indicator.

**Scope (rev-2 operator change 2026-08-17).** Dashboard-only, spanning
THREE surfaces:

1. **HA Lovelace URA v6 dashboard** — `ha_config_set_dashboard`
   EXTENDING the existing dashboard (do NOT replace). Follow the
   home-assistant best-practices skill for card selection and
   `entity_id` (not `device_id`) usage.
2. **HA Lovelace URA v8 dashboard** — same treatment as v6.
3. **PWA** (`~/Code/ura-dashboard-pwa`) — Presence card component change.

**NO** URA-side code change to any census producer, sensor, or dispatch
payload. No change to `camera_census.py:1502-1580`.

**Files.**

- HA URA v6 dashboard (edited via `ha_config_set_dashboard`) — swap
  the "on property" headline source from
  `sensor.universal_room_automation_persons_on_property_exterior` to
  `sensor.exterior_person_tracks_active`; add a conditional card or
  template chip so when the linker is `unavailable` OR
  `switch.ura_security_coordinator_exterior_path_tracking` is off, the
  card falls back to the naive sensor and annotates "degraded"; add a
  divergence chip when `linker_value != naive_value` (e.g. "tracks=1 ·
  raw=3").
- HA URA v8 dashboard — same edit shape as v6.
- PWA: `~/Code/ura-dashboard-pwa/src/…` (Presence card, exact file
  determined at build) — same source-swap + G1 fallback + divergence
  indicator.
- URA repo: **NO code changes.**

**Re-scope assessment (rev-2).** D3 is no longer "PWA-only trivial";
it now touches two HA dashboards + PWA. Two options:

- **Option A — keep D3 folded into this cycle.** Justification: the
  work is still all display-layer, the acceptance criteria are per-surface
  variants of the same three checks, and the Tier 2-DB reviews for D1/D2
  don't materially change (D3 has zero URA code diff). Marginal cost is
  one additional pass across 3 surfaces at build time.
- **Option B (recommended for operator consideration) — split D3 into
  its own small follow-up card `EXTERIOR-DASHBOARD-KEEPBOTH-1`.**
  Justification: keeps this cycle's blast-radius on the census producer
  (D1+D2) and lets D3 land on its own cadence, especially since HA
  dashboard edits typically want their own eyes-on live-check per
  surface. Recommend the split unless the operator prefers to keep the
  bonus attached.

**Default:** carry D3 in-cycle (Option A) but explicitly flag the split
option in the build brief so the operator can call it during dispatch.

**Knobs.** None.

**Acceptance criteria (per surface: HA v6, HA v8, PWA).**

- **Verify:** URA-side `git diff` for D3 is empty.
- **Verify:** HA dashboards were EXTENDED, not replaced — the
  pre-existing cards are all still present (compare card list against
  the pre-deploy snapshot recorded in the README).
- **Live (dashboard):** with linker active and naive == linker (probe
  baseline case), each surface's headline shows the linker value; no
  divergence badge.
- **Live (discriminating):** simulate G1 by turning
  `switch.ura_security_coordinator_exterior_path_tracking` off — each
  surface shows the naive value AND a "degraded" annotation (NOT 0
  while the naive is > 0). Contrast: if a card shows 0, G1 is not
  wired on that surface.
- **Live (discriminating):** when a real 1-walker-across-3-cameras
  event occurs (opportunistic post-deploy), each surface reads 1 (via
  linker) AND the divergence badge shows `raw=3`. If both read 3, the
  headline source is still naive on that surface.

---

## 5. Numbers-get-knobs table

| Number | Rung | Home | Why (one line) |
|---|---|---|---|
| `CENSUS_PEAK_SUSTAIN_SECONDS = 15 s` | 1 | `const.py:2705` | Measurement-quality gate; changing it warrants review. UNCHANGED. |
| `CENSUS_DECAY_STEP_SECONDS = 300 s` | 1 (retired) | `const.py:2697` | Dead after D1. Leave with tombstone comment. |
| `CONF_CENSUS_HOLD_INTERIOR` | 2 | options flow | Per-deployment freshness/robustness trade; operator legitimately tunes after observing detector cadence. Post-deploy 3 → 1 min. |
| `CENSUS_FACE_RECOGNITION_WINDOW_SECONDS = 1800 s` | 1 today; should promote to 2 (out of scope) | `const.py:2711` | Noted in research §5 change #12 — deferred. |
| `_face_lookup_missing_count` (D2) | n/a (diagnostic, PER-TICK) | payload attr | Not a knob; a counter. |
| `_peak_refresh_suppressed_count` (D1) | n/a (diagnostic, LIFETIME) | payload attr | Not a knob; a counter. Positive discriminator for D1's empty-house acceptance. |
| Dashboard divergence threshold | n/a (D3, display-only) | HA cards + PWA | Not a URA knob. |

**Kill-switch semantics.** No new kill switches. D1's mechanism is
delete-only (no way to "turn the slope back on"); if a regression
appears, the rollback is the deploy-level version pin. D2's
states-lookup has no kill switch — the failing-closed path IS the
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
| **D2 states-lookup fix (rev-2)** | Two small helpers, `hass.states.get`-based (face) + registry-enumerated map (last_camera). Mirrors shipped v5.78.0 `_has_any_suffix_stripped`. | Revives a defence that has fired 0×/7 d. Prerequisite for any face-based dedup ever working AND for `EXTERIOR-DWELL-LOITER-1`. | Small. New code is a well-tested pattern. Fail-CLOSED policy is safer than today's silent no-op. NO Frigate unique_id fabrication (rev-1 F1 corrected). | **GO.** Cross-cycle unblock alone justifies it. |
| **D3 dashboard (rev-2 re-scoped)** | HA URA v6 + HA URA v8 + PWA source swap + G1 fallback + divergence badge on each surface. | Surfaces the correct 1-walker-reads-1 headline on all three operator dashboards, not just the PWA; keeps the naive as a conservative floor per KEEP-BOTH. | Low but not zero (now three surfaces × three checks). No URA-side code change. HA dashboard edits done via `ha_config_set_dashboard` EXTEND (per home-assistant best-practices skill). | **GO with option to split.** Default: fold into cycle. Recommend to operator: split into `EXTERIOR-DASHBOARD-KEEPBOTH-1` follow-up card if they'd rather keep this cycle's blast-radius on the census producer. |

**No deliverable is dropped.** No fancier alternatives were considered
worth speccing — D1's alternative (extract `CensusHoldDecayService`) was
explicitly parked as a v4.7.18 follow-up with a documented evidence
trigger. D2's alternative (registry-mediated `async_entries_for_device`)
was considered in the plan-review response and rejected in favour of the
parsimonious `hass.states.get` pattern that mirrors shipped v5.78.0.

---

## 8. Plan Completion Tracking (mandatory)

Post-implementation, account for each of:

- D1 code changes (branches removed, payload extended, sensor attrs
  extended) — complete / partial + reason.
- D1 post-deploy operator config tune (3 → 1 min) — done / pending
  (this is a discrete step AFTER live-validation, not part of the
  deploy).
- D2 states-lookup at all 4 sites (3 face + 1 last_camera) — complete /
  partial + reason.
- D2 registry-enumeration of `frigate_*_last_camera*` — the observed
  person key set (recorded in the build's fix-up doc or README).
- D3 outcome per surface: HA URA v6 dashboard, HA URA v8 dashboard,
  PWA — deployed / pending. If split into
  `EXTERIOR-DASHBOARD-KEEPBOTH-1` follow-up card, link the card.
- Any deferrals: `identified_count > 4` diagnostic (new card),
  `CensusHoldDecayService` extraction (follow-up trigger),
  `CENSUS_FACE_RECOGNITION_WINDOW_SECONDS` rung promotion.

---

## 9. Recall

- "Census accuracy cycle"
- "Census decay separation"
- "Fresh-face states-lookup fix"
- "Exterior dashboard KEEP BOTH v6 v8 PWA"
