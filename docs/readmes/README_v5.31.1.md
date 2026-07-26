# URA v5.31.1 — Small polish batch (post-v5.31.0)

Patch release bundling the accumulated small-cycle work so the energy-savings
unification (#7) can proceed as its own clean Tier-2-DB cycle from a deployed base.
All items are display-only or dead-code removal — no decision-logic or money-path change.

## What ships

1. **`wifi_guest_floor` accuracy (backlog #10a).** The guest-VLAN floor *attribute*
   read 2 on an empty house. Tightened the recency window 24h → 4h
   (`WIFI_GUEST_RECENCY_HOURS`, reused — a real guest's phone appears in the last
   hours of a visit, not the last day) and extended `NON_GUEST_HOSTNAME_PREFIXES`
   with common IoT hostnames (roku/chromecast/google-home/nest/echo/hue/roomba/…)
   that look phone-ish on a shared SSID. **Display-only** — the value is still
   excluded from the headline census count (`camera_census.py:2222-2226`), so this
   cannot change occupancy or HVAC behavior.

2. **Delete dead `AutomationModeSelect` (backlog #10c).** The per-room
   `select.<room>_automation_mode` entity had **zero consumers** (no coordinator,
   test, dashboard, config-flow, or PWA reference — grep-confirmed). Removed the
   class + registration. The live on/off `switch.<room>_automation`
   (+ `_ai/_climate/_cover_automation`) controls are untouched — those remain the
   real automation toggles the PWA/ura-v8 surface.
   - **Registry residue (operator, harmless):** the ~40 existing
     `select.<room>_automation_mode` entities will show `unavailable` / `restored`
     until bulk-removed via the entity-registry UI at your convenience. Left in
     place deliberately (Bug Class #46 — no runtime cleanup of foreign registry rows).

3. **Test-suite pollution fix (backlog #9).** Two systemic test-ordering polluters
   fixed: (a) `test_zzz_v318` installed empty-`__path__` package stubs collected last,
   clobbering real submodule imports (all 14 suite ERRORS + ~5 failures); (b) a
   `MagicMock` voluptuous installed via `setdefault` won when it lost the import race
   (13 config-flow failures). Full suite: **44 failed + 14 errored → 26 failed +
   0 errored** (32 recovered, `test_freeze_floor` now green in-suite). The residual 26
   are a categorized, deterministic set (16 per-file datetime-awareness defects +
   10 genuinely pre-existing) — filed for a dedicated follow-up, out of this scope.

4. **Docs.** QUALITY_CONTEXT.md **Bug Class #61** (cross-coordinator re-assertion —
   one coordinator's guard defeated by another writer, e.g. reconciler vs fan cooldown)
   and **#62** (grep-only test overstates coverage). Planning docs filed:
   `PLANNING_energy_savings_unification.md` (the queued #7 spec) and
   `BACKLOG_2026-07-26_small_cycles.md` (10-item ledger).

## Review provenance
- #10a / #10c-b built by `ura-builder` (census tests 98/98; grep-confirmed dead-select
  has no consumers). #9 root-caused + fixed independently. Both agents independently
  observed the identical 26-failure residual baseline — cross-confirming no new
  regressions from either change.
- Tier: hotfix batch (display-only + dead-code + tests + docs; no decision-logic change).

## Live Validation — Acceptance Hypotheses (Shipwatch)

- **H1 — Clean boot.** Zero URA `ERROR` lines post-restart; 41 config entries `loaded`;
  `sensor.ura_presence_coordinator_presence_house_state` available. Window: 15 min.
- **H2 — Dead select gone, live switches intact.** `select.<room>_automation_mode`
  entities show `unavailable`/restored (no new instances); `switch.<room>_automation`
  and the `_ai/_climate/_cover_automation` switches remain available and togglable.
  Window: 15 min.
- **H3 — wifi_guest_floor tightened.** On an empty house,
  `sensor.universal_room_automation_persons_in_house` `wifi_guest_floor` attribute
  trends toward 0 (vs. the prior stale 2); headline `identified_count` unchanged by
  this edit. Window: next empty-house period.
</content>
</invoke>
