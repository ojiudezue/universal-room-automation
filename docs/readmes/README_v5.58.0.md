# v5.58.0 — UniFi Protect Person-Detection Legs for Perimeter Alerting

Interim step before the CameraResolver multi-integration cycle: the 9
perimeter + 3 egress cameras' person alerting gains registry-derived
Protect `*_person_detected` legs (+`_2`) alongside the Frigate base and
`_2` sensors. Protect is an independent detection engine (different
model, different failure modes) that was previously discarded.

- Coverage: 7/9 perimeter + 3/3 egress gain Protect legs — incl. the
  rear/utilities PTZs recovered via channel-suffix stripping (the two
  misses are non-UniFi hardware: Reolink porch, Amcrest overhead).
- One physical event across up to four legs (frigate, frigate_2,
  protect, protect_2) = exactly ONE alert (camera-key collapse through
  cooldown + in-flight + linker canonical keys; end-to-end tested).
- disabled_by-filtered registry derivation; EVENT_HOMEASSISTANT_STARTED
  rescan for late-loading integrations; INFO per-camera leg-coverage
  inventory at boot (kill-switch-gated); shared person-suffix strip
  helper unifying key/snapshot derivation.
- Kill switch: PERIMETER_PROTECT_PERSON_LEGS_ENABLED=False → byte-
  identical subscription set.

Reviews: 2 framing-disjoint (SHIP both) + fix-up closing all MED/LOW
incl. two test-authority gaps caught by the reviewer's novel mutations;
8-site mutation ledger all red-verified. Suite 8301 passed, 21
pre-existing failures name-stable.

## Live Validation (prospective)
- **Live:** boot log shows the per-camera leg inventory (7 perimeter +
  3 egress with protect legs).
- **Live:** next organic perimeter person → ONE alert regardless of
  which engine(s) fired; diagnostic shows one track.
- **Live:** zero URA ERROR lines first hour.

## Validated 2026-08-07 post-restart
v5.58.0 live; zero URA ERROR lines. clean boot, exterior census 0, house home_night; leg-coverage inventory + one-alert proof ride the next organic event.
