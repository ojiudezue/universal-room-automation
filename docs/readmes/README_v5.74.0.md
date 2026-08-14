# URA v5.74.0 — Circling-severity verification + zero-dispatch tripwire (CIRCLING-SEVERITY-1) + room-device area inheritance (D3-AREA-INHERIT)

## CIRCLING-SEVERITY-1 (Tier 2-DB: plan review + 3 framing-disjoint reviews)

The founding case (2026-08-08: circling track, alert_count=0) was traced and **verified
fixed-by-CONSOL-1** — the alert-hours existence gate that zeroed it was removed in v5.73.0 and the
contextual-severity table now owns the outcome. This cycle ships the proof and the tripwire:

- **Founding-case regression suite** — exact 5-hop replay through the real ExteriorTrackLinker
  (adjacency graph loaded; topology-precondition test guards the oracle), wire-in anchored at the
  sole `note_alert_dispatched` call site.
- **27 severity pins** — all 9 house states × 3 persons_home values for (perimeter, circling),
  verbatim against the CONSOL-1 §6 table (CRITICAL fail-safes, HIGH override, arriving MEDIUM,
  waking CRITICAL, guest constant read at test time).
- **`sensor.perimeter_circling_zero_dispatch_24h`** — diagnostic tripwire enforcing INV-M
  ("a circling track never ends at alert_count=0 in any non-guest state, linker+NM enabled"):
  5-min poll, 24h lookback (both rung-1 constants), counts circling tracks with zero dispatches
  and lists offenders. This is the enforcement machinery for the residual dispatch-loss modes
  (NM exception, teardown short-circuit, cancelled delayed dispatch) — all three
  mutation-anchored to their production sites. `unavailable` when the linker isn't wired
  (distinct from healthy 0). Live tripwire, not a durable ledger: open offenders are lost on
  restart by design.
- **Reading the tripwire:** a non-zero value is *investigate*, not *code bug* — a circling track
  whose dispatches were all suppressed by the 300s per-camera cooldown legitimately flags
  (Review B-LOW-2).
- **Known gap, operator decision pending (CIRCLING-LABEL-1):** for the dominant 2-camera
  alternating shape, pages go out at hops 1-2 (pass_by rows) but the track only *becomes* circling
  at hop 3, where cooldown blocks dispatch — so circling loops page but are never labelled HIGH
  as circling. INV-M holds; the labelling semantics await the operator's A/B/C pick.

Reviews: plan review FIX-PLAN-FIRST (rev-2 fixed 3 missed dispatch-loss paths pre-build);
A SHIP / B SHIP / C DO-NOT-SHIP (hollow-anchor variant #5: test simulated the teardown instead of
driving it) → fix-up 22d291841 re-routed AC-4 through the real `async_teardown`; orchestrator
personally re-drilled the cancel-loop neuter (1 red, restored, 40 green, tree clean).

## D3-AREA-INHERIT (Tier 1)

New room devices inherit their area from CONF_AREA_ID via
`device_registry.async_update_device(area_id=…)` in the shared base entity's
`async_added_to_hass` — only-when-unset (operator manual assignments always win), durable past
HA 2026.9 (`suggested_area` is deprecated there; not used). First review caught that the original
per-entity stamp would have been a silent production no-op (device created by the first-registering
platform); fix moved it to the base class.

## Acceptance criteria

- **Test:** perimeter package 40 tests (5 founding + 27 pins + 8 tripwire), test_d3_area_inherit.py.
- **Live:** loads, zero URA errors post-restart.
- **Live (tripwire, C's compensating control for the poll-shim source anchor):**
  1. `sensor.perimeter_circling_zero_dispatch_24h` present in the entity registry within 60s of restart.
  2. Its `last_updated` advances within CIRCLING_DIAG_POLL_INTERVAL_MINUTES+1 (=6) minutes of restart.
  3. Attributes show `poll_interval_minutes: 5`, `lookback_hours: 24`.
- **Live (D3):** next NEW room created inherits its configured area automatically (organic; no
  existing device is touched).
- **Live (organic):** next genuine circling episode in home_day/home_evening pages (pass_by rows
  today; HIGH-as-circling pending CIRCLING-LABEL-1).

## Live Validation

### Validated 2026-08-12 (v5.74.0 boot 23:34:47 CT)

| # | Criterion | Result | Evidence |
|---|---|---|---|
| L1 | Loads, zero URA errors | **PASS** | error_log post-boot: boot-transient WARNINGs only; no URA platform-setup errors |
| L2 | Tripwire sensor registered ≤60s of boot | **PASS** | Registered 23:34:59 (12s after boot marker). NOTE: actual entity_id is `sensor.ura_security_coordinator_perimeter_circling_zero_dispatch_24h` (HA device-name prefix) — the plan's bare `sensor.perimeter_circling_zero_dispatch_24h` was aspirational. Docstring corrected in follow-up |
| L3 | Poll tick fires ≤6min of boot | **PASS** | `last_reported` 23:38:08 (~3.3min post-boot) — poll ran; value stayed 0 so `last_changed` correctly static |
| L4 | Attribute pins | **PASS** | `poll_interval_minutes: 5`, `lookback_hours: 24`, `offenders: []`, state `0` (linker wired — would read `unavailable` otherwise) |
| L5 | D3 area inherit | **ORGANIC (open)** | Next NEW room created must inherit its configured area; no existing device touched (verified only-when-unset guard in review) |
| L6 | Circling episode pages | **ORGANIC (open)** | Next genuine circling in home_day/evening pages (as pass_by rows today; HIGH-as-circling pending CIRCLING-LABEL-1 operator pick) |

Boot transients observed and dismissed: rooms holding occupancy 60s, energy sensors "not loaded
yet", camera_census early-scan warnings — all standard boot ordering, all recovered.
