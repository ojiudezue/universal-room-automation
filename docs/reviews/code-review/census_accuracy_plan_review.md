# Plan Review — CENSUS-ACCURACY-1 (Tier 2-DB, single adversarial pass pre-build)

**Plan:** `docs/planning/PLANNING_census_accuracy.md` @ 89af06222
**Probe:** `docs/planning/AUDIT_census_accuracy_probe.md` @ 4f67edfea
**Exterior ruling:** `docs/planning/AUDIT_exterior_census_supersession.md` @ eb2caa3c8
**Verdict:** **PLAN-NEEDS-FIXES** — one HIGH (D2 unique_id fabrication) blocks build; one MEDIUM (site-count inflation) plus two LOW acceptance-criteria tightenings. Fix in the plan; do not defer to the builder.

---

## 1. Independently-derived emission-site list (D1)

Method: `grep -n "_peak_house_timestamp\|_peak_house_camera_count\|_peak_property_timestamp\|_peak_property_count\|_store_peak"` over `camera_census.py`.

All writes to peak state — 7 sites, all inside `_apply_hold_decay` / `_store_peak`:

| # | file:line | Path | Post-D1 outcome |
|---|---|---|---|
| 1 | `camera_census.py:2555` (via `_store_peak`) | `peak_ts is None` — first-observation latch | UNCHANGED |
| 2 | `camera_census.py:2567` (`_set_pending`) | Upward, unsustained pending raise | UNCHANGED |
| 3 | `camera_census.py:2585` (`_store_peak`) | Sustain-window met → promote pending to peak | UNCHANGED |
| 4 | `camera_census.py:2598` (`_store_peak`) | Property zone instant-latch upward | UNCHANGED |
| 5 | `camera_census.py:2603` (`_store_peak`) | `fresh == peak` self-refresh | **DELETE (D1 target)** |
| 6 | `camera_census.py:2628-2629` | House post-hold `decay_steps` linear slope reset | **DELETE (D1 target, part of :2621-2632 block)** |
| 7 | `camera_census.py:2635-2636` | Property post-hold instant-drop reset | UNCHANGED (D1 adopts this shape for house) |

Init-only assignments at `:985-988` are constructor defaults (not decay-emission writes).

**Conclusion:** the plan's D1 file-list (`:2601-2605` + `:2621-2632` + payload/sensor additions) covers every peak-refresh / decay site. **No N+1th emission site.** The v5.5.3 lesson does not fire here.

Control-flow check on the `fresh == peak` deletion: if the entire `elif fresh_count == peak:` block is removed, control falls to the trailing `else:` (`fresh_count < peak`); its guard `if pending_since is not None and fresh_count < pending` no-ops for the equality case, then flows into the `elapsed >= hold_seconds` branch, which post-D1 does an instant drop. Behaviorally identical during the hold window (peak unchanged, count=fresh) and after (instant reset). Plan's alternative (keep return, remove only the `_store_peak` call) is simpler and also correct; either is safe.

## 2. Independently-derived face-site list (D2)

Method: `grep -n "_last_recognized_face\|last_camera"` over `camera_census.py`.

Actual construction sites — **4, not 5** as the plan claims:

| # | file:line | Kind | Function |
|---|---|---|---|
| 1 | `camera_census.py:2399` | `f"sensor.{base_name}_last_recognized_face"` | `_get_face_recognized_persons` |
| 2 | `camera_census.py:2432` | `f"sensor.{base_name}_last_recognized_face"` | `_get_face_recognized_persons_fresh` |
| 3 | `camera_census.py:2752` | `f"sensor.{base_name}_last_recognized_face"` | `_get_unrecognized_camera_count` (Step 1) |
| 4 | `camera_census.py:3059` | `f"sensor.frigate_{person_slug.lower()}_last_camera"` | `_get_face_recognized_person_names` |

**Line 2385 is a docstring**, not a construction site. The plan's "5 sites" figure counts it. Not a leak (no site missed), but the plan will confuse the builder.

## 3. Live registry probe (measure-before-you-build gate on D2) — RUN NOW

Read `/Users/okosisi/ha-config/.storage/core.entity_registry`, filter platform=frigate:

- Face sensors (23 total, all with `_2` suffix). Example unique_id:
  `01KM239Z8ZQWQTN1D9CV5JRA7V:sensor_recognized_face:ArmCrestASH41B`
- `frigate_*_last_camera` (5 total). Example:
  `01KM239Z8ZQWQTN1D9CV5JRA7V:sensor_global_face:Oji`

**The plan's hypothesised unique_id is wrong.** Plan §D2 code snippet uses:
```python
ent_reg.async_get_entity_id("sensor", "frigate",
    f"{camera_info.device_unique_id}_last_recognized_face")
```
Actual Frigate convention is `"<instance_id>:sensor_recognized_face:<CamName>"` where `<instance_id>` is the Frigate server ULID (`01KM239Z8ZQWQTN1D9CV5JRA7V`) and `<CamName>` is the Frigate config's camera object name in **original mixed case** (`ArmCrestASH41B`, `back_yard`, `family_room`, `ReolinkStudyBPorchPTZ`). Neither is derivable from `camera_info.entity_id` (all-lowercase, HA-slugged) nor from a URA-owned constant. Same shape issue for `_last_camera`: `sensor_global_face:<PersonName>` (capitalized, `Oji` / `Ezinne` / `Jaya` / `Ziri`), not `person_slug.lower()`.

This is a category error the plan justifies via "precedent already in v5.79.0 D3 (`presence.py:5354-5390`)". That precedent works because URA **defines** the unique_id (`f"{DOMAIN}_person_{slug}_phone_left_behind"`). Frigate is external; URA cannot fabricate its unique_id.

---

## 4. Findings and required plan edits

### F1 — HIGH — D2 unique_id snippet is a fabrication (BLOCKS BUILD)

**Symptom.** Plan §D2 gives the builder a concrete snippet (`f"{camera_info.device_unique_id}_last_recognized_face"`) that will return `None` for every Frigate face sensor in the live registry. A builder following the spec verbatim would ship a fresh-face path that fails on every lookup — indistinguishable from today's dead behaviour — and could ship it green if tests fabricate the same wrong unique_id.

**Evidence.** Live registry probe (§3 above): actual unique_id is `<instance_id>:sensor_recognized_face:<CamName>` with a Frigate ULID prefix and a mixed-case camera object name; plan's construction misses both prefix and case.

**Required plan edit.** Rewrite §D2 to use ONE of:

- **Preferred (parsimonious with v5.78.0 shipped pattern):** resolve via `_strip_disambiguation_suffix` + `hass.states.get` on both the un-suffixed and `_2`-suffixed variants of `sensor.<base>_last_recognized_face` / `sensor.frigate_<slug>_last_camera`. This mirrors the `_has_any_suffix_stripped` treatment shipped in v5.78.0 (`camera_resolver.py:317-327`) for `_person_count_2` and needs no registry knowledge. Fail-CLOSED direction is preserved (both lookups miss → no `-1` credit).
- **Alternative (registry-mediated):** use `entity_registry.async_entries_for_device(device_id)` (`device_id` obtainable from `camera_info` if it carries it, else via the binary_sensor's `RegistryEntry.device_id`) and filter for `entity.entity_id` ending in `_last_recognized_face`. Robust to any Frigate unique_id format churn.

Either way: DELETE the current snippet from the plan. State fail-CLOSED explicitly (missing lookup → no `-1`, `_face_lookup_missing_count += 1`). Update the D2 acceptance test `test_d2_resolves_last_recognized_face_via_registry` to seed a fixture with the `_2` suffix and assert the shipped resolver returns that entity_id (drill: unregister → assert counter increments, no free `-1`).

Sub-note: `frigate_*_last_camera` has only 5 registered entities (one per tracked person including a "Default"). If the plan retains a person-name→entity resolution, the correct mapping is `person_slug.title()` (capitalized) for the `<PersonName>` fragment — but the parsimonious pattern above bypasses this entirely.

### F2 — MEDIUM — D2 site count is 4, not 5

**Symptom.** Plan §0.3 and §D2 list `camera_census.py:2385, 2399, 2432, 2752, 3059`. Line 2385 is a docstring (`"""Scans all Frigate cameras for sensor.*_last_recognized_face entities."""`), not a construction. Actual construction sites: `:2399, :2432, :2752, :3059` — 3 face + 1 last_camera.

**Required plan edit.** In §0.3 and §D2 "Files", replace the 5-item list with the 4-item table in this review's §2. Reword "at 5 sites" → "at 4 sites (3 face + 1 last_camera)". If §D2's helper `_resolve_face_entity_id(camera_info)` is extracted, all 3 face sites collapse to 1 helper call; `_last_camera` gets its own tiny helper.

### F3 — MEDIUM — Empty-house discriminator can be spoofed by outdoor cameras

**Symptom.** Plan's D1 live observation ("residents away until Wed PM → census reaches 0 and stays 0") assumes zero interior camera person_count firings during the observation window. Frigate on outdoor cams (porch, backyard, driveway) will fire on wildlife, wind, mail carriers, delivery. If any interior Frigate cam does the same (kitchen door, family_room glare), the observation shows a legitimate rise-and-decay that looks identical to a stuck-tail defect.

**Required plan edit.** Add to D1 acceptance criteria:
> **Live-precondition guard.** The empty-house observation is valid ONLY during intervals where `sum(<interior Frigate>._person_count) == 0` continuously for `hold + 1 tick`. Intervals containing any interior camera firing are recorded as "inconclusive" (not fail). Enumerate the interior camera list from `camera_manager.get_all_frigate_cameras()` at build time (record in the README).

Also add a positive discriminator so the observation doesn't just require an absence: assert `peak_refresh_suppressed_count > 0` during any interval where a systematic-error tail WOULD have fired pre-D1 (i.e., the payload counter is directly measuring what we deleted). Contrast: if the counter is 0 across the whole observation window AND the previous 7-day probe showed 74.5% elevated-time from the tail, D1's delete isn't in the code path — a wiring miss the plan's other checks don't catch.

### F4 — LOW — Consumer threshold: nobody-home → AWAY becomes newer/faster

**Symptom.** Plan §3.2 states "no consumer becomes newly permissive in a dangerous direction". True for `count > 0` consumers (security, phone-left-behind). But `presence.py:1059-1063` (nobody-home → AWAY) fires when `census_count == 0`. Post-D1 that transition fires within `hold + 1 tick` instead of `hold + linear-decay-slope`. Under a plausible different failure (stale mmWave in a room while a resident sits silently), AWAY could fire while a person is home.

Not blocking — the whole cycle exists to make census tell the truth, and AWAY-while-someone-present is a presence-layer failure, not a census failure. But the plan's acceptance criteria don't discriminate a legitimate-fast AWAY from a wrong AWAY.

**Required plan edit.** Add to D1 "Live (safety check)":
> First census-driven AWAY transition post-deploy is corroborated by BLE person absence AND person_coordinator status. If AWAY fires while any resident's BLE says home OR tracking_status ≠ AWAY, log an "AWAY-with-resident-present" audit event and note in the README's write-back table. (No block on ship — this is an observability requirement to catch a regression, not a gate.)

### F5 — LOW — INV-DECAY-HONEST wording

**Symptom.** Invariant reads "if no live interior camera has asserted a body for the last `hold + 1 tick`". "Live" and "asserted a body" are colloquial; a defect that fires because a stale/unavailable `_person_count` sensor was misread would still LOOK compliant. The invariant should reference the same public counter D1 adds (`peak_refresh_suppressed_count`) or an equally-observable signal.

**Required plan edit.** Reword: "for every census tick where `sum(interior Frigate _person_count) == 0` continuously for the preceding `hold + SCAN_INTERVAL_CENSUS`, `unidentified_count == 0` AND `peak_held == False`." Ties the invariant to a measurable precondition, matches F3's live guard.

### F6 — INFO — INV-PEAK-NO-SELF-REFRESH is well-formed

The detach-drill (assert `peak_ts` unchanged across 10 steady-fresh ticks) directly falsifies the defect it names. Cannot be satisfied by a wrong implementation that still refreshes `peak_ts` on `fresh == peak`. Good.

### F7 — INFO — `CENSUS_DECAY_STEP_SECONDS` tombstone

Verified: only reader is `_apply_hold_decay:2624`, which D1 deletes. Tombstone-with-comment (plan's stated preference) is safe. `grep CENSUS_DECAY_STEP_SECONDS custom_components/` returns only `const.py` + `camera_census.py:2624` (the site being deleted).

### F8 — INFO — GUEST entry preservation is intact

Verified: `presence.py:4886` is Path A corroborator only (v5.79.0). D1 makes `unidentified_count` numerically smaller/fresher; Path A becomes STRICTER (harder to corroborate a phantom guest), not looser. INV-GUEST-LEAD (from v5.79.0) is not endangered.

---

## 5. Non-blocking observations

- **D2 helper reuse.** Extracting `_resolve_face_entity_id(camera_info)` (plan's stated intent) is the right call; the 3 face sites are near-identical. Add a `_resolve_last_camera_entity_id(person_slug)` sibling for `:3059` for symmetry.
- **Payload extension `count_as_of` ISO.** Add a note in D1 that `count_as_of` should be `dt_util.utcnow().isoformat()` at DISPATCH time, not the compute-start time, so consumers reading it against their own `dt_util.utcnow()` can compute lag correctly.
- **Diagnostic counters lifecycle.** `peak_refresh_suppressed_count` and `_face_lookup_missing_count` — clarify in plan whether these are lifetime (monotonic since coordinator start) or per-tick reset. Plan text conflicts: D1 implies lifetime; D2 says "per-tick reset". Downstream operators reading the payload should not have to guess. Recommend LIFETIME for D1 (matches "was systematic-error tail firing"), PER-TICK for D2 (matches "is this tick's lookup healthy").

---

## 6. Verdict

**PLAN-NEEDS-FIXES.** Blocking: F1 (D2 unique_id fabrication) — the builder cannot succeed following the current snippet. F2 (site-count inflation) is a doc bug the builder will hit immediately. F3/F5 tighten D1's discriminator so the empty-house observation actually discriminates. F4 adds a lightweight AWAY-audit observation.

Apply the plan edits above (they are all small — ~30 lines of plan doc) and re-dispatch to build. All findings are in-scope for a plan-review round; none require another planning session.
