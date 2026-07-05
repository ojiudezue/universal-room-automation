# URA v5.8.0 — Reconcile-on-Return: re-assert a room's desired state when an actuator comes back online (Tier 3)

Closes the **silent-actuator failure** that v5.7.2 made *visible*. When a room's light/fan relay is `unavailable`, URA detects occupancy fine but its `turn_on`/`turn_off` no-ops against the dead device; when the relay reconnects it stays stuck in whatever state it was left in until the next occupancy event. v5.8.0 adds a per-room `ActuatorReconciler` that, on every `unavailable → available` transition, re-asserts the room's **live-computed** desired state for that single entity — never a stored snapshot.

## Origin
AV-closet light didn't auto-on at entry / auto-off at exit (2026-06-30) because the Shelly relay was offline the whole occupancy window; on reconnect it stayed stale. D1 (v5.7.2) made the outage visible; D2 (this cycle) recovers from it. Design: `docs/planning/PLANNING_reconcile_on_return.md`.

## What ships (scope: lights + fans ONLY — covers and climate explicitly out of scope)
New file `actuator_reconciler.py` — a per-room reconciler owned by `UniversalRoomCoordinator`. On an actuator's `unavailable → available` edge it recomputes the room's desired state for THAT entity via a thin `resolve_desired_state` (reads occupancy / is_dark / sleep-mode; mirrors the canonical `_control_lights_entry`/`_control_lights_exit` / temperature-fan handlers' **control** surface) and re-asserts just that entity through `automation._safe_service_call`. Twelve guard clauses (§2 of the plan):

- **Live re-assert** (D2.3) — single-entity `light.turn_on/off` / `fan` call, not the whole set; NO-OP if already in the desired state.
- **Guards** (D2.2) — manual_mode off, boot-settle done + grace elapsed, per-entity debounce + hourly cap, occupancy known, not a cover/climate.
- **Boot-settle coalesce + grace** (D2.7, CORE) — a batch reconnect collapses to ONE resolver pass per room per 2.5 s window; a construction-age grace covers the reload path too.
- **Zero synchronous DB writes** (D2.8, CORE) — all telemetry via the batched activity-log; no per-reconcile DAO write (June-2026 write-flood precedent).
- **Rebuild-hook re-arm** (D2.9, CORE) — reconciler listener re-armed inside `_update_signal_subscriptions` so an in-place rebuild can't orphan it (Bug Class #50).
- **Branch-table parity** (D2.10, CORE/GATING) — resolver agrees with the canonical handlers on every legal cell; `None` (no opinion) only where the handler also wouldn't act (Bug Class #53).
- **Flap detector + quarantine** (D2.11) — a chronically flaky actuator (canary: AV-closet Shelly1PMGen3) is quarantined after 4 availability transitions / 120 s; released ONLY after 10 min continuous-available (stability-proven, never a bare timer); RAM-only; surfaced as `reason:"flapping"` on the v5.7.2 sensor.
- **Observability + control** (D2.12) — per-room `Auto-Recovery` switch (default ON, **enabled by default** so the dry-run lever works out of the box: flip OFF → watch `would_reconcile` → flip ON); `RoomReconcileSensor` (per-room) + `ReconcileHealthSensor` (house-wide); collapsed `reconcile_advanced` config section with a named-bucket `flap_sensitivity` dropdown (relaxed/normal/aggressive).

## Review / gate (Tier 3)
Four framing-disjoint reviews (A local-correctness / B integration-lifecycle / C test-authority-via-source-mutation / D adversarial-completeness). All returned FIX-FIRST: **2 CRITICAL + 3 HIGH + 7 MEDIUM fixed.** Dominant class was #53 resolver control-surface parity (was reconciling `alert_lights`/`humidity_fans` the canonical handlers never control; dropped fan sleep/vacancy policy). Reviewer D caught the only path A/B/C + the build all missed: the post-boot grace was inert on the **reload path**. Orchestrator independent verification mutation-tested 3 load-bearing sites (grace, humidity-parity, D2.9 wiring — the last surfaced + fixed OV-1, a source-grep test that a semantic neuter slipped past), and re-ran Reviewer D's completeness enumeration after the grace fix → **SHIP** (no N+1 arming site). Review doc: `docs/reviews/code-review/v5.8.0_reconcile_on_return.md`. Pre-deploy zero-bugs gate: no conflict markers; `py_compile` clean; **65 reconcile tests + 20 config-flow tests pass**; full suite at the documented **35-failed / 14-error ordering-flake baseline — zero new failures** (verified against a clean `develop` worktree).

**Falsifiable invariant (holds across cold-boot / reload / mid-grace-rebuild):** on any actuator `unavailable → available` edge, the reconciler performs zero synchronous DB writes, issues ≤1 resolver pass per room per coalesce window, never actuates during boot-settle or its grace, never touches a quarantined entity except via the stability-release path, and never dispatches a service call for a room whose `Auto-Recovery` switch is OFF (while still computing `would_reconcile`).

---

## Acceptance

```yaml
version: 5.8.0
hypotheses:
  - id: H1
    name: ura_v580_deployed
    description: URA v5.8.0 is the running HACS-installed version.
    oracle: home_assistant
    query: { kind: home_assistant.state_attribute, entity: update.universal_room_automation_update, attribute: installed_version }
    expected: { condition: "==", value: "v5.8.0" }
    window: { first_check_after: 10m, confirm_after: 1h, alert_if_violated_after: 6h }
  - id: H2
    name: no_error_storm
    description: No recurring URA error after the reconciler ships.
    oracle: home_assistant
    query: { kind: home_assistant.log_count, search: "universal_room_automation", period: 24h }
    expected: { condition: "<", value: 5 }
    window: { first_check_after: 1h, confirm_after: 24h, alert_if_violated_after: 72h }
  - id: H3
    name: reconcile_sensors_live
    description: The per-room reconcile sensor publishes reconciles_today.
    oracle: home_assistant
    query: { kind: home_assistant.state_attribute, entity: sensor.av_closet_room_reconcile, attribute: reconciles_today }
    expected: { condition: "!=", value: "unknown" }
    window: { first_check_after: 10m, confirm_after: 1h, alert_if_violated_after: 24h }
  - id: H4
    name: no_reconcile_write_spike
    description: The batched activity-log write-rate stays within baseline during induced reconnects (D2.8).
    oracle: home_assistant
    query: { kind: home_assistant.log_count, search: "reconciled ", period: 1h }
    expected: { condition: "<", value: 200 }
    window: { first_check_after: 1h, confirm_after: 24h, alert_if_violated_after: 72h }
```

> Shipwatch note: HA adapter stub backlogged → resolves `pending` until it ships. Verify entity/attribute names live before trusting `confirmed`.

## Live Validation — to populate post-restart (write-back rule)
- **L1 Deploy healthy:** `update.universal_room_automation_update` installed_version = `v5.8.0`; zero URA ERROR lines in boot log.
- **L2 Reconcile sensors present:** every room with lights/fans exposes `sensor.<room>_room_reconcile` (initial `reconciles_today=0`); `sensor.house_reconcile_health` present.
- **L3 Auto-Recovery switch:** `switch.<room>_auto_recovery` visible per-room (enabled by default), defaults ON, survives restart (Bug Class #52: an `unavailable` last-state falls back to ON). Flip OFF → next reconnect populates `would_reconcile` but emits no service call; flip ON → reconciles normally.
- **L4 Real reconcile (AV-closet canary):** on the next Shelly `unavailable → available`, `sensor.av_closet_room_reconcile.recent_reconciles`/`reconciles_today` shows the entry and the light state matches `occupied AND is_dark`; grep `home-assistant.log` for the `reconciled ` line.
- **L5 Flap quarantine:** if the AV-closet Shelly thrashes, `sensor.av_closet_unavailable_entities.flapping_entities` lists it with `reason:"flapping"` and ZERO `reconciled <av_closet>` lines while quarantined; clears + exactly one reconcile after 10 min stable.
- **L6 Coalesce (D2.7):** a batch reconnect (≥3 room actuators ≤2 s apart) increments `reconcile_coalesced_count` by (N-1); one resolver pass per room per window.
- **L7 No write spike (D2.8):** batched activity-log write-rate within pre-deploy baseline during induced reconnects.
