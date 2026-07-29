# URA v5.35.0 — Stuck-Signal Watchdog (stage 1: detect + discount + notify)

Closes the class behind four incidents (foyer-fisheye 11h GUEST, Master-mmWave flap
phantom, Ezinne 3-day frozen tracker, Jaya face latch): *presence-implying signals
frozen in the asserted state with zero corroboration, silently.* Built per the
CATALOG verdict (`CATALOG_cross_correlation_primitives.md`): **extend the thrice-proven
"asserted-too-long ⇒ demand corroboration ⇒ act" shape (P22/P24/P18), don't roll a
new framework.** Detection + census discount + NM notification ONLY — no actuation,
no auto-remediation (stage 2, trust-gated).

## What ships
- **D1 — census stuck-camera check:** per-Frigate-camera `person_count>0` held
  unchanged ≥ `STUCK_CAMERA_HOURS` (3.0) with zero interior corroboration (tier1/
  mmWave/motion/BLE by area) → camera **discounted from the census input** (the C7
  peak floor then decays naturally) + NM notify with remedy ("reload Frigate entry").
  Safety rails (Review A): area-less cameras are never silently discounted (skip+WARN);
  areas with NO interior sensors are **notify-only** (a lone stationary guest in a
  camera-only area cannot be census-dropped). Fail-open: any watchdog exception clears
  the discount set — census byte-identical to pre-watchdog.
- **D2 — duty-cycle stuck detector (notify-only):** binary sensor ≥85% asserted over
  60 min (≥20 ticks) without PIR corroboration (≥2 transitions in-window or 1 in the
  last 5 min) → NM notify + diagnostic. **Deliberately NOT wired to the exclusion
  set** (Review B H-1): a sleeping person IS a ~100% mmWave duty cycle — exclusion
  would vacate sleeping bedrooms through the home_night trust gap. Exclusion graduates
  in a later cycle behind a house-state gate.
- **D3 — frozen-tracker check:** device_tracker frozen at `home`/`unknown` ≥
  `FROZEN_TRACKER_DAYS` (2.0) → NM notify (no auto-prune). **Predicate redesigned in
  review** (A-CRIT-1): the original tracker-vs-person disagreement rule was
  structurally blind to the motivating incident (a frozen tracker *drives* the person
  state, so they always agree). New rule: frozen-at-home is anomalous per se; sibling-
  tracker disagreement is message context, not a gate. Ezinne repro is a named test.
- **D4 — NM surface for the four existing silent detectors:** Fix #9 continuous-on
  (P22), max-active failsafe (P24), zone stale-occupancy force-away (P18), actuator
  flap-quarantine (X7, with paired recovery notify only after a prior stuck notify).
  All emits per-day dedup-latched (local date), kill-switched by
  `CONF_STUCK_SIGNAL_NM_ENABLED` (options flow, default on — silences notifications
  without disabling detection).
- All four gated behind the canonical presence **boot-settle** predicate (same source
  as ActuatorReconciler) — no cold-boot alert storms.

## Review provenance
`docs/reviews/code-review/v5.35.0_stuck_signal_watchdog.md` — Tier 2, two framing-
disjoint reviews. **Both returned DO-NOT-SHIP on the first pass:** 3 CRITICAL (D3
predicate blind to its own motivating incident + tests that reimplemented rather than
drove production code + a test codifying the bug) and 5 HIGH (D2 exclusion could
vacate sleeping bedrooms; missing boot-settle gate; PIR-blip shield; D1 false-discount
holes). All fixed; orchestrator independently re-verified via **real source mutation**
(inverted the D3 predicate → 5 tests fail; restored → 18/18 pass) plus grep-verified
D2-no-exclusion and the D1 fail-open call site, and personally patched a missed M-3
(per-tick task spam in D3).

## Live Validation — Acceptance Hypotheses (Shipwatch)
- **H1 — clean boot.** Zero URA errors; no stuck-signal NM emits within the boot-settle
  window. 15 min.
- **H2 — no false alerts in steady state.** Over 24h of normal operation, no
  `stuck_signal` NM notifications for healthy sensors/cameras/trackers (the house
  currently has none known-stuck). Window: 24 h.
- **H3 — census unchanged.** `persons_in_house` behavior identical to v5.34.1 in
  normal operation (fail-open + no-stuck = no discounts); `stuck_cameras` attr = []. 1 h.
- **H4 — synthetic drill (validator-run).** With `STUCK_CAMERA_HOURS` temporarily
  lowered on a test basis OR the next organic stuck event: stuck camera → discounted +
  one NM notification with remedy; recovery after reload. Window: organic/on-demand.
- **H5 — D4 surfaces fire on their existing detectors.** Next time Fix #9 / failsafe /
  zone-stale / flap-quarantine trips organically, an NM notification accompanies the
  existing log line, once per day per signal. Window: organic.
</content>
