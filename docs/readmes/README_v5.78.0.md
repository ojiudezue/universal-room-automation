# URA v5.78.0 — LOST dissolution (evidence matrix), memory writers, and the away-veto census hole

The cycle that closes the AWAY-BLOCK-1 cul-de-sac on **all three** of its paths. Tier 2-DB:
plan + 2 plan-review rounds + operator design checkpoint + 3 framing-disjoint build reviews
(A SHIP / B SHIP / C FIX-THEN-SHIP, all findings resolved) + orchestrator re-drills.

## The problem this closes

On 2026-08-13 the house held `home_day` for 82 minutes with everyone away. Three independent
causes, all fixed here:

1. **`LOST` was overloaded** (origin: v4.7.14.1 H3/Gap C). A person confidently away but without
   a BLE fix was stamped LOST and *excluded from the trusted denominator* — so away-inference
   went vacuous exactly when it was needed. H3 was right to distrust stale fallbacks; it was
   wrong to lump confidently-away in with genuinely-unknown.
2. **The census clause blocked the veto** (Gap A). Path α required `census_count == 0`, but
   census identity = BLE-home ∪ face-recognized — so a **forgotten phone on the counter** kept
   the count ≥ 1 and blocked the away transition, even though H2 had correctly excluded that
   person from the denominator. H2 fixed the person half; the census half stayed open.
3. **Camera-less rooms produced false phone-left-behind flags** (Gap B). The detector required a
   *face-recognized* camera sighting within an hour; someone working in an office with no camera
   was flagged as having abandoned their phone and dropped from the denominator.

## What shipped

**Evidence matrix (D2a).** `tracking_status` is decided by a 16-row matrix over three axes —
GPS · WiFi · BLE — where **absence is a first-class axis value**, read live per tick (never
cached: app installs, permission grants/revokes and phone swaps change a person's branch on the
next evaluation). Confidence follows the operator's evidence hierarchy: all-sources-agree 0.99 →
GPS+WiFi 0.97 → local-nets-departed 0.95 → GPS-only 0.92 → WiFi-only 0.90 → **BLE-silence-only
0.82** (`BLE_SILENT_ONLY_AWAY_CONFIDENCE`, deliberately below path-α's 0.9 so a BLE-only person
cannot solo-release the house). Case-(b) phone-on-charger is `ACTIVE + home` — never LOST — so it
still blocks away. `LOST` now means only *no signal*. Sub-cases ride a `tracking_reason` string
attribute; **no new enum value** (H2 adoption: the vocabulary did not grow).
- BLE `silent` requires **provable scanner liveness** (fleet detecting other devices in-window);
  an unproven fleet yields `indeterminate` → no away vote. Accused-witness discipline.
- No-signal / `entity_missing` (pre-matrix guard) can **never** contribute an away vote (I-α).
- Path-β's relaxed predicate + `lost_away_persons` retired (D2b) — case-(a) reads ACTIVE at source.

**Gap A (D8).** Path α now gates on **camera-provable** evidence — `unidentified_count == 0 AND
face_recognized_count == 0` — restoring the clause to its documented intent. No new knob: face
freshness is already bounded (`CENSUS_FACE_RECOGNITION_WINDOW_SECONDS` = 1800 + the tracker
cross-check, which is fail-open when a person entity is missing — documented upper bound).

**Gap B (D9).** Phone-left-behind now consults **room occupancy**: live mmWave/PIR in the room
where BLE places the person suppresses the flag. Conservative by construction — the change can
only make the flag fire *less*.

**Memory writers (D4–D7).** Four episodic writers, rate-bounded by construction, zero consumers
on any actuation path (memory-ineligible boundary is a build gate): `phantom_retro` (fan-release
correlated, detector-independent — captures the latches D2 gating misses), `away_transition_blocked`
(coalesced one row per block-episode, **restart-discharge wired at `PresenceCoordinator.async_setup`**
so no open episode leaks across a boot), `tracker_trust_excluded` (60 s debounce), and
`house_state_transition` (first-tick-post-boot suppressed).

**Observability (D2c) — three attributes on existing sensors, zero new entities:**
`face_recognized_count` + `path_alpha_gate_source` on the house-state sensor (post-Gap-A,
`census_count` no longer gates — publishing both prevents the next debugger blaming the wrong
number), `tracking_reason` + `tracker_sources` per person, and Gap-B corroboration outcome on the
phone-left-behind binaries.

**Riders:** guest-FP A1 diagnostic classifier (exact-match on `tracking_reason`, not substring);
EV cleanup — removed the two dupe `ev_charge_rate_*` sensors (strict subset of the status sensor's
live power attrs, zero consumers) and wired optional per-plug real power.

## Knobs
Ten, **all rung 1 (module constants), zero new entities, zero config-flow fields** — operator
ruling. `BLE_SILENT_ONLY_AWAY_CONFIDENCE`, `PHANTOM_RETRO_{RELEASE_WINDOW_S,MIN_HOLD_S,ENABLED}`,
`AWAY_BLOCK_EPISODE_{MIN_HOLD_S,MAX_OPEN_S,ENABLED}`, `TRACKER_TRUST_{MIN_HOLD_S,WRITER_ENABLED}`,
`HOUSE_STATE_TRANSITION_WRITER_ENABLED` (+ the D9 corroboration pair). Gap A adds none.

## Acceptance criteria
- **Test:** matrix fixture (all 16 rows) + memory writers (25) + observability (19) + vocabulary
  pin (7) + Gap A/B suites. Suite: **24 failed / 9162 passed** vs develop's **25 / 9078** — zero
  new failures, +84 tests, one pre-existing failure fixed.
- **Live L1:** boot clean, zero URA ERROR lines.
- **Live L2 (the point of the cycle):** with everyone genuinely away and no camera evidence, the
  house transitions to `away`. Evidence: `sensor.ura_presence_coordinator_presence_house_state`
  shows `all_tracked_persons_away: true`, `face_recognized_count: 0`, `veto_path: active`.
- **Live L3:** per-person `tracking_reason` / `tracker_sources` render on the person surfaces and
  match each person's real axis inventory (Oji/Ezinne carry GPS; Ziri is BLE-only via IRK).
- **Live L4:** `face_recognized_count` and `path_alpha_gate_source` present on the house-state
  sensor; `census_count` still published but visibly not the gate.
- **Live L5 (memory):** after a real block or fan-release phantom, the corresponding episode type
  appears in `memory_episodes`; no writer floods (row counts stay bounded).
- **Live L6 (organic):** a forgotten-phone-at-home day no longer blocks the away transition.
- **Note (review B):** the earlier prediction that zone bucket counts would visibly shift is
  **wrong for the populations this cycle affects** — case-(a)/case-(b) locations are zone-level
  (`away`/`home`), not room-level, so no zone bucket movement is expected.

## Live Validation
(to be written back post-restart)
