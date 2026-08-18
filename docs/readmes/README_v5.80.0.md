# URA v5.80.0 — Interior census accuracy: decay separation + the `_2`-suffix fresh-face fix

Cycle 2 of the census/guest arc. Where v5.79.0 fixed **guest mode** (guest rooms lead, dead
oracle repaired), this fixes the **interior count itself** — the number that stayed wrong on
purpose after v5.79.0. Tier 2-DB: probe-gated plan (rev-2) + plan review + build + **3
framing-disjoint reviews** (A SHIP / B SHIP-with-fix / C SHIP) + fix-up.

## The problem this closes

A read-only probe (`AUDIT_census_accuracy_probe.md`) measured *why* the interior census
over-counts, and the answer rejected the assumed fix and pointed at two real ones:

1. **The decay was the cost centre.** Of all the time the census read above the true resident
   count, **74.5% had zero live camera evidence** — a pure hold/decay tail. Worse, the peak
   **self-refreshed** whenever `fresh == peak`, so a systematically-wrong value never decayed at
   all; only transient spikes did. Wrong sign on both axes.
2. **Fresh-face de-duplication was structurally dead.** The `−1` credit that subtracts a
   face-recognized resident from the camera body count had fired **zero times in 7 days**,
   because the code string-built `sensor.{base}_last_recognized_face` while every live entity
   carries the `_2` suffix (the missed Frigate-1→2 migration). Same for the `last_camera` lookup.
3. **The dedup *repair* was rejected on evidence.** BLE-cancel is not broken code — it's a
   camera-area coverage gap (an operator config task), not a build. Dropped from scope.

## What shipped

**D1 — decay separation.** Deleted the peak self-refresh on `fresh == peak` and the house-zone
linear-decay slope; the house zone now uses the same instant-drop the exterior zone already had.
The hold window (`CONF_CENSUS_HOLD_INTERIOR`) still governs *when* decay starts — D1 changes the
*shape*, not the hold. Publishes `peak_held` / `peak_age_seconds` / `count_as_of` /
`peak_refresh_suppressed_count` on the census signal + `persons_in_house` attributes, so a held
count is distinguishable from a fresh one and the suppression is observable. `CENSUS_DECAY_STEP_SECONDS`
is tombstoned (its only reader was the deleted slope).

**D2 — `_2`-suffix fresh-face fix.** The 4 string-built Frigate face/last_camera sites now resolve
via `hass.states.get` (base then `_2`) and a registry-enumerated person→camera map (keyed on the
Frigate first-name, e.g. `oji`, not the URA slug `oji_udezue`). **Fail-CLOSED**: a registry/state
miss grants no `−1` credit — the safe direction (a wrong direction would under-count). This revives
face-based dedup, and is the shared prerequisite for the parked exterior dwell-loiter work.

**Non-goals (explicit):** no guest-logic changes (shipped v5.79.0), no code dedup/BLE-cancel repair
(probe rejected — it's config), no exterior census producer swap (KEEP BOTH, per
`AUDIT_exterior_census_supersession.md`). D3 (exterior dashboard wiring across URA v6 + v8 + PWA)
folds into this cycle but wires *after* D1/D2 land, since it consumes D1's new attributes.

## Knobs

**None new.** `peak_refresh_suppressed_count` / `face_lookup_missing_count` are diagnostic counters,
not operator knobs. `CENSUS_DECAY_STEP_SECONDS` retired. Post-deploy, `CONF_CENSUS_HOLD_INTERIOR`
may be tuned 3→1 min via the options flow — a knob turn, no code.

## Acceptance criteria — the empty house is the decay test

Residents are away (until Wed), which makes the **discriminating decay test free**: an empty house
should reach census 0 and **stay 0**, with no self-refresh.

- **Test:** `test_census_accuracy_d1_d2.py`. Baseline: develop 25 failed / 9194 passed; branch tip
  **name-diff EMPTY**.
- **Live L1:** boot clean, zero URA ERROR.
- **Live L2 (decay, discriminating):** census reaches 0 and stays 0 while the house is empty, AND
  `peak_refresh_suppressed_count > 0` appears over a period the old code would have self-refreshed —
  the positive proof the suppression path executed (not merely that the count happened to be 0).
  Guarded by `interior person_count == 0` for hold+tick so an outdoor cam firing on wildlife can't
  spoof it.
- **Live L3 (fresh-face revival):** on first occupancy, `face_recognized_count > 0` when a resident
  is face-recognized (was structurally 0 before); `face_lookup_missing_count` does not climb
  unboundedly (fail-closed working, not silently missing).
- **Live L4:** census compared against ground-truth headcount on return — expected to read **closer
  to true** than v5.79.0 (the decay tail removed), though full accuracy also needs the camera-area
  coverage config.

## Live Validation

### Validated 2026-08-18 (~00:33 CT, post-restart) — house EMPTY (residents away until Wed)

The empty house is the discriminating decay test, so L1/L2 are provable now; L3/L4 need occupancy.

| # | Criterion | Result | Evidence |
|---|---|---|---|
| L1 | Boot clean, zero URA ERROR | **PASS** | system_log ERROR count for universal_room_automation: 0 |
| L2 | Decay honest (discriminating) | **PASS** | `sensor.universal_room_automation_persons_in_house` = 0, `peak_held: false`, `peak_age_seconds: 0`, **`peak_refresh_suppressed_count: 22`** — positive proof the self-refresh suppression path executed (not merely that the count is 0). count_as_of is a single ISO stamp (dual-clock fix confirmed). |
| L3 | Fresh-face revival | **ORGANIC-PENDING** | Needs occupancy to see face_recognized_count > 0. WATCH: `face_lookup_missing_count: 12`/tick on an empty house is higher than expected — fail-closed (safe, no wrong credit) but the face path isn't resolving on ~12 cameras; interpret on return, carded as CENSUS-FACE-MISS-WATCH-1. |
| L4 | Accuracy vs ground-truth headcount | **ORGANIC-PENDING** | Compare on return (Wed) — expected closer to true than v5.79.0 (decay tail removed). |

**Cycle stays open until L3/L4 land on occupancy.**

