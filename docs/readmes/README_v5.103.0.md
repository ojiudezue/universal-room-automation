# URA v5.103.0 — Appliance onboarding + categorization (v1b) + room-classification read-model

**Shipping:** 2026-09-15
**Tier:** v1b = Tier 2 (2 framing-disjoint reviews); Option C D-C1 = Tier 1-2 (1 review); both orch-verified.
**Cards:** APPLIANCE-MGMT-REFINE-1 (v1b) · ROOM-CLASSIFICATION-CONSISTENCY-1 (D-C1, closes the card)

MINOR bump: a **new operator-facing capability** — appliance onboarding + categorization. Also carries the
already-shipped **v5.102.1** census thread-safety fix (activates on this restart) and a test-only fixture fix.

---

## D1 — Appliance onboarding + categorization (v1b) — the operator-visible feature

Builds on v1a's read-only census. The operator can now **declare and categorize appliances** through the
CM options flow:

- **Onboarding editor** (CM → Appliance Coordinator): add / edit / remove per-appliance records, reusing
  the zone-picker dynamic-menu pattern. Each record: `name`, **functional domain**
  (`media_av | kitchen | laundry | climate | cold_chain | water | cleaning | other`), optional `room`, and
  per-role entity refs (power / energy / control / state) via entity selectors.
- **Net-new appliances** (a TV, an AV receiver — things not in any URA room config) can be **added**;
  URA-owned entities keep showing up automatically (v1a). A declared record's functional domain flows into
  `sensor.ura_appliance_coordinator_appliance_census` (shows its real domain, not `other`).
- **Cross-integration grouping** (the operator's de-dup): declaring one record that names a ThinQ device +
  a SPAN circuit + a room entity collapses those into ONE appliance — the operator-declared answer to the
  no-auto-join constraint.
- **Records have a stable uuid `id`** (review A-HIGH-1/2 fix): edit/remove resolve by id, and a stale menu
  (a second browser/options session) re-renders rather than editing or deleting the wrong record.
- **Entity exclusivity:** saving a record naming an entity already in another record is rejected (operator
  sees a translated error). Empty-shell records (no entities) are rejected.
- **No CM reload storm:** appliance-record saves are in `OPTIONS_RELOAD_SUPPRESS_KEYS` — iterative
  onboarding applies in place, no parent-entry reload (the watchdog hazard). The coordinator re-reads
  records live on the next census tick.

### Review (Tier 2, 2 framing-disjoint) — all fixed + orch-verified
Found and fixed: index-as-identity wrong-record edit/delete (→ stable uuid), and **three hollow test
anchors** (census tests now drive the real flow; reload-suppress tests are listener-driven behavioral, not
comment-greps; the AST-slice guard now covers bare `CONF_*`). Orchestrator independently re-ran the M2
reload mutation → `test_records_only_save_does_not_reload_cm` RED then GREEN on restore. +3 net tests.

### Acceptance criteria — Live
- **Live:** CM options flow shows an "Appliance Coordinator" step; adding a record (name + a domain + an
  entity) persists and the census shows it with that `functional_domain`.
- **Live:** an onboarding save does NOT reload the CM entry (sibling coordinator entities keep their
  `last_changed`); no parent-reload watchdog event.

## D2 — Room-classification read-model accessor (Option C D-C1) — closes ROOM-CLASSIFICATION-CONSISTENCY-1

`get_room_classification(hass, room_entry) → {function, flags, outdoor, infrastructure}` +
a `classification` attribute on `sensor.ura_<room>_signal_inventory`. Additive, read-only, changes no
existing consumer.

**Honest scope:** this is **infrastructure / a read-model** — the operator-visible surface is one
diagnostic attribute that no dashboard or automation consumes yet. The card's real anti-entropy value
shipped in v5.102.0 (the `docs/architecture/ROOM_CLASSIFICATION.md` map). D-C1 is a foundation a future
consumer (e.g. a dashboard "rooms by classification" view) can opt into. Shipped per operator go; reviewed
SHIP with one MEDIUM fixed in-cycle — the accessor is a **pure reader** of `_outdoor_zones_cache` (it does
NOT write it, which would have risked seeding a stale empty set into the safety consumer that owns the
cache) and fails open so it can never blank the host sensor's other attributes.

**Card closure:** D1 (docs, v5.102.0) + D-C1 (accessor) shipped; D2 (basement wiring) / D3 (outdoor-coercion
retire) parked with config-trigger revival; Option B (unify all flags) rejected. ROOM-CLASSIFICATION-CONSISTENCY-1 → done.

### Acceptance criteria — Live
- **Live:** `sensor.ura_<room>_signal_inventory` carries a `classification` attribute; the Patio (Outside
  zone) shows `outdoor: true`; a guest room shows `guest` in flags.

## Also in this release
- **v5.102.1 (census timer thread-safety)** — the fix is in this release's history and activates on this
  restart: no more off-loop `async_create_task` frame warning from the census refresh timer.
- **Test-only fix** — the v1a freshness fixture (`_FakeState`) now uses production's `dt_util.utcnow()`
  time source, fixing a latent env-coupled failure under `.venv-ha` (aware−naive `TypeError`). Production
  freshness was correct (v5.102.0 live-validated 147 fresh / 73 unknown).

## Verification performed pre-deploy
| Check | Result |
|---|---|
| Conflict markers | none |
| `py_compile` (all shipped source) | OK |
| room-classification + appliance v1a + config-flow v1b + cm-reload suites (`.venv-ha`) | **88 passed** |
| Orchestrator M2 reload mutation (independent) | RED → restored GREEN |
| Branch discipline | merged + deployed from develop (verified) |

---

## Validated 2026-09-15 (post-restart, ~12:04–12:12 America/Chicago)

| # | Criterion | Result | Evidence |
|---|---|---|---|
| D1 | Census populated + live-updating, commands nothing | **PASS** | `sensor.ura_appliance_coordinator_appliance_census` = 197 → 239 across two 30s ticks (tracks live entities repopulating post-restart); `stale_max_age_s=300`; enable switch `on`; no appliance-originated service call in the log. |
| D1 | Appliance Coordinator onboarding step | **IN-SUITE + no-error-at-load** | The CM options step + record editor are covered by the v1b flow tests (add/edit/remove/reject, all flow-driven post-fix); no `config_flow` ERROR at setup. Live UI click-through not exercised via API. |
| D1 | Records save does not reload CM | **IN-SUITE (behavioral)** | Orchestrator-verified: removing `CONF_APPLIANCE_RECORDS` from `OPTIONS_RELOAD_SUPPRESS_KEYS` turns `test_records_only_save_does_not_reload_cm` RED. Not separately live-exercised (needs a real options save). |
| D2 | `classification` attribute + Patio outdoor | **PASS** | `sensor.patio_signal_inventory.classification = {function: common_area, flags: [shared], outdoor: true, infrastructure: false}` — Patio `outdoor: true` confirms the accessor reads the Outside zone via the snapshot, not the coercion. |
| v5.102.1 | No RECURRING off-loop census-timer warning | **PASS** | The v5.102.0 every-30s `async_create_task from a thread` flood is GONE; census re-pushes via the `@callback → async_write_ha_state` path (state advanced 197→239 with no recurring frame warning). |
| — | No URA setup ERROR | **PASS** | `system_log` level=ERROR search `universal_room_automation` = 0 entries. |

**Entity-id note:** the real entities are `sensor.ura_appliance_coordinator_appliance_census` (CM-prefixed) and `sensor.<room>_signal_inventory` — recorded so future validation doesn't read `None` from a guessed id.

### RESIDUAL FINDING (live-only) — carded, not blocking
A **single boot-time** `async_create_task from a thread other than the event loop` warning remains, reported
at `sensor.py:8121 → await super().async_added_to_hass()`.

**Correction (investigated 2026-09-15):** my first read blamed the `AggregationEntity` base's
`async_added_to_hass`. A static trace **falsified** that — the base creates no task (its `super()` chain
reaches an empty `Entity.async_added_to_hass`; its room-poll uses `async_schedule_update_ha_state()` with no
force_refresh). The reported line is a **frame-walker artifact** (the nearest URA frame on the stack when an
off-loop call fires elsewhere), not the producer. The **true off-loop producer is unidentified** — the boot
traceback rotated out before capture. **Risk correction:** on the running HA (core-2026.9.2) this guard
*raises a RuntimeError today* for a custom integration (not a 2027 warning) — non-fatal only because it's
swallowed in the dispatch/worker thread; it fires once at boot, so **practical impact is LOW now**, high only
if a hot-path producer ever dispatches off-loop. Carded as `AGGREGATION-ENTITY-ADDED-THREAD-SAFETY-1`, moved
to **investigating** with a measure-first gate: capture the full boot traceback on the next restart to name
the real producer before any build. Not a v5.103.0 regression (v5.102.1's recurring census-timer task IS
fixed; this is a separate, pre-existing boot-time off-loop dispatch).
