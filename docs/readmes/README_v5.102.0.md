# URA v5.102.0 — Appliance census (v1a) + perimeter leg-superset trip-wire

**Shipping:** 2026-09-14
**Tier:** 3 program, slice v1a (Tier 2-DB reviewed) + a Tier-1 perimeter observability rider
**Cards:** APPLIANCE-MGMT-REFINE-1 (v1a) · TEST-1 (perimeter-leg-superset-warn, batched)

MINOR bump: a **new coordinator dimension** arrives — a first-class `ApplianceCoordinator` under
'Add Coordinator'. v1a is deliberately **read-only** (census only); categorization+onboarding (v1b),
cost (v1c), and anomalies (v1d) follow as staged slices.

---

## D1 — Appliance census (v1a): a first-class passive coordinator

A new **passive** `ApplianceCoordinator` (`evaluate()→[]`) that produces a read-only appliance census
and **commands nothing**. It appears under 'Add Coordinator' with its own enable switch and device;
its own anomaly identity is reserved for v1d.

- **3-source discovery** (unioned): (1) SPAN circuits read from the Energy coordinator's
  `SPANCircuitMonitor` (registered **after** Energy so the monitor exists; lazy read, degrades if
  absent), (2) operator-declared appliance records (`CONF_APPLIANCE_RECORDS`, default `[]`, read side
  only — the editor is v1b), (3) URA-owned room entities (fans, humidity_fans, power_sensors,
  climate_entity, room_media_player, lights, covers).
- **No auto-merge (v1a decision):** one census record per unique unclaimed `entity_id`; nothing is
  dropped (no-drop invariant). `device_id` is deliberately NOT used to merge — it is not a reliable
  appliance boundary (a ThinQ washer = 1 device/many entities; a 2-channel Shelly = 1 device/2
  appliances). All grouping is operator-declared, in v1b.
- **`sensor.ura_appliance_census`** — read-only diagnostic, `_attr_should_poll=False`, driven by a 30s
  interval, `appliances` excluded from the recorder (`_unrecorded_attributes`) to avoid recorder
  pressure. Power reads normalized through `_units.power_state_to_w` (kW→W). Per-appliance
  `current_power_w` sums multi-leg power refs; `freshness` uses the worst (oldest) ref and ignores
  `unavailable`/`unknown`, with a boot-settle window.

### Review (Tier 2-DB, 3 framing-disjoint) — all fixed
5 HIGH found and fixed: no-drop leak (device_id over-collapse dropped 27 live entities), power-unit
bypass (Bug Class #30), recorder-flood polling, a hollow sensor wire-in anchor (+ false "turns RED"
comments in source), and a near-vacuous commands-nothing test. Orchestrator independently re-ran the M1
mutation → both wire-in anchors RED then GREEN on restore (residue 0). 27/27 appliance tests.

### Acceptance criteria — Live (to validate post-restart)
- **Live:** `sensor.ura_appliance_census` exists, state = census record count, `appliances` attribute
  lists records with name/domain/roles/source_tags/current_power_w/current_state/freshness.
- **Live:** a URA room fan appears with `source_tags` including `ura_config` and needed no onboarding.
- **Live:** the coordinator appears under 'Add Coordinator' (enable switch `switch.ura_appliance_coordinator_enabled` present, default on).
- **Live:** zero ERROR from `universal_room_automation` attributable to the appliance coordinator; the
  census commands nothing (no service calls originate from it).
- **Live:** no recorder "state attributes exceed maximum size" WARNING for `sensor.ura_appliance_census`.

### Deferred (carded)
- Multi-room-same-power-sensor attribution → `APPLIANCE-CENSUS-MULTI-ROOM-POWER-SENSOR-1` (v1b).

---

## D2 — Perimeter leg-superset boot trip-wire (TEST-1, batched)

`perimeter_alert.py`: a boot-time shadow diff that warns if the resolver's camera leg set is not a
superset of the legacy set — a live trip-wire against silent camera-coverage shrinkage. Additive; no
alerting control-flow change. 4 tests + wire-in anchor + mutation drills (built/reviewed earlier;
shipped here on the batched deploy).

### Acceptance criteria — Live
- **Live:** on boot, if the resolver leg set ⊇ legacy set, no warning; a shrinkage would log the named warning.

---

## Verification performed pre-deploy
| Check | Result |
|---|---|
| Conflict markers | none |
| `py_compile` (all shipped source) | OK |
| appliance + resolver-legs tests | **55 passed** |
| Orchestrator M1 mutation (independent) | both wire-in anchors RED → restored GREEN, residue 0 |
| Full suite | +12 passes vs baseline, no new appliance/perimeter-surface failures |

**Process note:** this release recovered from a branch mishap — 39 commits (this cycle's plans,
reviews, kanban, the v1a merge, and TEST-1) had accumulated on `feature/perimeter-leg-superset-warn`
instead of develop; `git push origin develop` had been silently no-op. develop was fast-forwarded to
capture all of it (clean, develop was a strict ancestor) before deploy.

---

## Validated 2026-09-15 (post-restart)

HA restarted 2026-09-15 ~00:01 America/Chicago; URA v5.102.0 activated via HACS.

| # | Criterion | Result | Evidence |
|---|---|---|---|
| D1 | Census sensor present + populated | **PASS** | Real entity is **`sensor.ura_appliance_coordinator_appliance_census`** (CM-prefixed — the prospective `sensor.ura_appliance_census` was wrong, same id-correction class as v5.101.2's TOU sensor). State = **220**, `appliances` attribute lists 220 records. |
| D1 | URA-owned shows up with `ura_config` | **PASS** | **194 of 220** records carry `ura_config` in `source_tags`; e.g. `fan.polyfan_dreo704s_wifi_studya` (Study A, state role, `current_state: off`). No onboarding step. Remaining 26 are `span`. |
| D1 | Power normalized to watts | **PASS** | `Span Right Fridge Power` → `current_power_w: 72.8` (W, via `_units.power_state_to_w`, not a raw kW misread). |
| D1 | Freshness discriminates | **PASS** | 147 `fresh` / 73 `unknown` — the `unknown` bucket is the fix working (unavailable/unknown states are NOT falsely reported `fresh`). |
| D1 | Enable switch present, on | **PASS** | `switch.ura_appliance_coordinator_enabled` = `on` (fresh post-restart). Coordinator appears under 'Add Coordinator'. |
| D1 | No recorder oversize WARNING | **PASS** | No `state attributes exceed maximum size` for the census entity; `_unrecorded_attributes={"appliances"}` keeps the ~65KB `appliances` blob out of the recorder. |
| D1 | Commands nothing | **PASS** | No appliance-originated service calls in the logbook/system log post-restart. |
| D2 | Perimeter leg-superset check | **PASS** | No boot error from the leg-superset warn path. |

### FINDING (live-only) → fixed in v5.102.1
**Thread-safety warning at `sensor.py:8121`:** the census refresh timer used
`async_schedule_update_ha_state(force_refresh=True)`, whose entity-update machinery spawned a task
off the event loop, tripping HA's frame guard ("`hass.async_create_task` from a thread other than the
event loop … may cause crash or data corruption"). The census functioned correctly regardless (state
220), but this is a real thread-safety defect **static review + tests missed** (the tests don't run the
real timer in the real loop — a live-validation catch). Fixed in **v5.102.1**: a `@callback` calling
`async_write_ha_state()` (in-loop, no task; the state recomputes in the property getters).

**Benign, unrelated:** a HomeKit "150 device limit" WARNING fired when the new enable switch pushed the
HomeKit bridge past 150 devices — a HomeKit-filter config matter, not a URA defect (operator may add the
switch to the HomeKit filter). Pre-existing `device_registry` deprecation warnings (HA 2027) are
unchanged and not from this cycle.

**Organic discriminator (met):** `sensor.ura_appliance_coordinator_appliance_census` exists post-restart
with a non-empty `appliances` attribute (220 records, 194 `ura_config`) and no recorder-oversize WARNING —
the `--revisit` criterion is satisfied.
