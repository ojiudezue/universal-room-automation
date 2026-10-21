# Plan review: PLANNING_camera_detector_hung_tripwire.md (Tier 2, one adversarial pass, 2026-10-21, commit 47a1a7c89)

Not HVAC. Camera-input health is presence-adjacent; checked against the IDENTITY_FUSION_CAMERAS_MANUAL `_2` resolver doctrine.

**Verdict: FIX-PLAN** (small; all fixes are in-plan edits)

## Verified (holds)
- `grep -rn detection_fps custom_components/` returns 0 hits, so nothing reads the fps stat today.
- `camera_census.py:180-258` checks availability only (status_2 at :238). A hung detector leaves `dark_now` False.
- REUSE anchors are correct: optimization.py:621, :641 (`_camera_input_dark_boot_ref`), :1058, :1073, :2020, :2816; const.py:4402-4403; binary_sensor.py:3276-3335; NM outer guard at :5522-5527.
- I1 and I2 are falsifiable. D0 closes the constant-healthy question (max non-zero run 5 min).
- Protect-only installs: the plan reuses the denominator==0 inert branch (:2873). OK.

## Findings
- **HIGH: missed emission site (Bug Class #53).** `optimization.py:5363-5384` `_is_camera_input_dark` exempts the fleet one-shot from the per-cycle findings cap (`OPTIMIZER_MAX_FINDINGS_PER_CYCLE`). §4 does not list it. If the cap drops the finding, the latch is already set and no page is ever sent. Add it as site 4. The §4 grep check ("exactly sites 1-3") would then mislead the builder.
- **MEDIUM: I1 "exactly one ... regardless of restarts" is false as designed.** The latch (`_detector_hung_fired`) and `_notify_dedup_state` (:5555) are both in RAM. Each restart or CM-reload OC rebuild during one long hang re-fires after FROZEN_S+BOOT_SETTLE (about 18 min). A 39 h hang with the measured restart cadence sends N pages. Fix: either restate I1 as "at most one per process lifetime" and accept repeat pages, or seed the latch from the last `notification_log` row for the kind. Pick one explicitly and test it.
- **MEDIUM: hardcoded entity id.** The manual (§`_2` rules, lines 54-74) says reads resolve through the registry, never a literal suffix. The status_2 precedent is itself a literal. At minimum, state the exception and log once if the entity id is absent from the entity registry, so the check is not silently inert after a Frigate re-add. Better: resolve via the Frigate config entry's registry entries (unique_id suffix `detection_fps`).
- **MEDIUM: D1 "entity missing → log once, do not fire" is ambiguous.** Does the state reset each tick, and does `unknown` at boot reset `value_since`? Specify: any non-numeric value resets it, and the first numeric value after boot starts the dwell. Otherwise a builder may carry a pre-boot value.
- **LOW: acceptance discriminator.** The host-down vs hang split is tested in-suite only. Make the staged daytime detector pause a required Live row, not an "or", because the frozen-on-hang mechanism has never been measured (D0 says so).
- **LOW: §7 kill switch.** `FROZEN_S=0` "disables", but the predicate `elapsed ≥ 0` fires immediately. Spell out `<=0 → return []` and test it (the test name exists, the semantics do not).

## Builder pitfalls
Missing the cap site. Widening the NM guard as a conjunction inside the predicate instead of the outer tuple test. Trusting `last_changed`. A rebuild test that reuses the same instance.
