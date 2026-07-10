# RESEARCH — SPAN Panel Integration Architecture (2026-07-10)

Scope: fact-base for hygiene re-audit items #1 (SPAN remap worksheet) and
#4 (3 orphaned DB circuit baselines). Read-only research; no code changes.

---

## Part A — SPAN integration state (upstream)

### A1. Which integration is canonical

- `SpanPanel/span` (github.com/SpanPanel/span) is the current HACS
  default. Forks (`sargonas/span`, `gdgib/span`, `cayossarian/span`,
  `mbbush/span-homeassistant`) are legacy / abandoned.
- `span-panel-api` (PyPI) is the underlying client library shared by
  the integration.
- A separate Gen3-only community integration exists for SPAN MAIN 40
  (gRPC-based). Not relevant here — our panels are MAIN 32-series.

### A2. Recent release timeline (per GitHub releases)

- **v2.0.8** 2026-05-19 — auto-reconnect after firmware upgrade.
- **v2.0.7** 2026-05-16 — door sensor stability, energy-stat spike
  prevention on reconnect.
- **v2.0.6** 2026-04-17 — By-Activity/By-Area dashboards, x-panel
  favourites.
- **v2.0.5** 2026-04-03 — current monitoring, services accept
  entity_id instead of UUID, i18n, circuit-switch bounce fix.
- **v2.0.4** 2026-04-01 — Grid Power sensor, sim moved to add-on,
  recorder growth reduction.
- **v2.0.3** 2026-03-16 — HA 2026.3.2 compat.
- **v2.0.2** 2026-03-15 — battery power sign, `-0W` normalization.
- **v2.0.1** 2026-03-09 — **breaking**: requires spanos2/r202603/05
  firmware; state values now lowercase (`DSM_ON_GRID` → `dsm_on_grid`);
  Energy Dip Compensation; WebSocket Topology API; EVSE/BESS
  sub-device support.
- **v1.3.1** 2026-01-21 — circuit-name-`None` reload-loop fix, spike
  cleanup service legacy-name support.
- **v1.2.x** — Circuit Name Sync introduced; flexible entity-naming
  patterns (friendly vs circuit-number).

### A3. Entity model — how circuits are identified

Two operator-selectable naming modes (v1.2+; still shipping in 2.0.x):

- **Friendly names (default, recommended by upstream)** —
  `sensor.span_panel_kitchen_outlets_power`. The `entity_id` derives
  from the SPAN-app circuit name and **is re-synced** when the
  operator renames a circuit in the SPAN app (this is what bit us in
  v4.7.32). `unique_id` is stable across renames per upstream docs.
- **Circuit numbers (stable)** —
  `sensor.span_panel_circuit_15_power`. `entity_id` is derived from
  the tab number and is invariant under SPAN-app renames.

Unmapped tabs: the integration synthesizes entities for tabs that
haven't been assigned to a circuit (`span_panel_unmapped_tab_N_*`).
Panel-prefixed variants exist for split panels
(`Span Left Unmapped Tab N Power`). Under v1.2+ Circuit Name Sync,
a real circuit is renamed the instant it's assigned — so a live
"Unmapped Tab N" entity always corresponds to a genuinely empty
slot. (This is the assumption v4.7.32's stale-baseline prune already
relies on — energy.py:4711-4726.)

### A4. Third-party / local-API viability

- Legacy MAIN 32 undocumented local endpoints (which the current HA
  integration depends on) are being **deprecated 2026-12-31**.
- New official **SPAN API** (documented, supported) is rolling out
  MAIN 32 first with firmware `r202603`, complete by end Feb 2026;
  MAIN 40 and other panels follow H2 2026.
- **SPAN Home On-premise** (browser app running on the LAN, talking
  to SPAN API) is now public-beta.
- Net: local access is NOT going away — it's transitioning from an
  undocumented endpoint to a documented one. Integration authors are
  already moving (`v2.0.1` firmware requirement = SPAN API path).
- Long-term: URA continues to consume via the SpanPanel HA
  integration — no direct API dependency of ours to migrate.

---

## Part B — URA repo cross-check

### B1. How URA consumes SPAN today

- Discovery + anomaly loop: `energy_circuits.py:90-153` scans
  `sensor.span_panel_*_power` entities (auto-discover) plus operator
  `extra_entities` (Emporia/Shelly), minus `exclude_entities`.
- Discovery keys the runtime dict by `entity_id`
  (`self._circuits: dict[str, CircuitInfo]` — energy_circuits.py:79).
- Anomaly detection: `MetricBaseline` per circuit, keyed at runtime
  by `entity_id` but **persisted with `scope = friendly_name`** —
  energy_circuits.py:155-166. This is the root of the rename bug.
- Persist: `energy.py:4620` writes all baselines to
  `metric_baselines` table.
- Restore (energy.py:4664-4785): loads rows, for each
  `metric_name='circuit_power'` row does a reverse lookup
  `circuit.friendly_name == row.scope` to re-attach to a discovered
  entity_id. Miss handling:
  - scope contains `"Unmapped Tab"` → auto-prune with reversible
    backup (energy.py:4725, `metric_baselines_pruned_backup`).
  - Otherwise → WARN only, `unmatched += 1` (energy.py:4728-4732).
    Baseline is dropped from memory this boot but **the DB row is
    kept**. Next boot repeats the WARN. Anomaly detection for that
    circuit degrades: the CircuitInfo exists (if re-discovered under
    the new name) but starts a fresh baseline with 0 samples —
    z-score checks gated by `sample_count >= CIRCUIT_MIN_SAMPLES`
    (energy_circuits.py:189) simply don't fire until it re-warms.
    No crash, no false alerts; feature just quietly re-learns.

Config surface: `CONF_ENERGY_CIRCUIT_AUTODISCOVER_SPAN`,
`CONF_ENERGY_CIRCUIT_EXTRA_ENTITIES`, `CONF_ENERGY_CIRCUIT_EXCLUDE_ENTITIES`
(energy_const.py:604-606).

### B2. Blast radius — is SPAN consumed anywhere else?

Grep of `custom_components/universal_room_automation/` for
`span_panel|_circuits.|circuit_power`:

- `energy.py` — baseline save/restore only.
- `energy_circuits.py` — the discovery + anomaly logic itself.
- `energy_pool.py:169, 176` — two hard-coded EVSE breaker entity_ids
  (`switch.span_panel_car_charger_breaker`,
  `switch.span_panel_garage_b_evse_breaker`) for EVSE
  pause/resume. **Not** baseline-related; would break independently
  if those breaker switches were renamed, tracked separately.
- Rooms/zones/optimizer: no direct SPAN awareness. Rooms consume
  generic power/energy sensors via room config; they don't care
  about SPAN keying at all.

**Conclusion:** SPAN circuit-name coupling is contained to the
energy-coordinator anomaly loop. Baseline-key blast radius is a
single subsystem (circuit power anomaly z-scores). No zone/room
regression risk from a re-key.

### B3. The 3 orphaned DB baselines

`'Battery Power'`, `'Span Left Subpanel Power'`,
`'Span Left Unknown Power'`:

- None contain the substring `"Unmapped Tab"` → not caught by
  v4.7.32's auto-prune → they log the "no matching circuit" WARN
  every boot (energy.py:4729-4732).
- Behaviour is benign: rows sit in `metric_baselines` unused; no
  new samples ever land against those scopes because there is no
  circuit whose `friendly_name` equals them any more. They cost 3
  WARN lines per boot and 3 unused rows in the table.
- **Are they worth work?** They will never self-heal (no automatic
  aging — the code only prunes "Unmapped Tab"). The minimal fix is
  either: (a) one-shot manual DELETE against those three scopes, or
  (b) extend the auto-prune list to include an operator-provided
  scope allowlist / an "unmatched for N boots" TTL. (a) is a 30-second
  DB op; (b) is a code cycle.

### B4. What a stable re-key would look like

Since v1.2+ SPAN exposes stable per-circuit unique_ids (upstream doc
confirms `unique_id` stays fixed across SPAN-app renames), URA could
key baselines on `unique_id` instead of `friendly_name`:

- On discover: fetch each `sensor.span_panel_*_power` entry from the
  entity registry (`hass.helpers.entity_registry`), read `unique_id`,
  store on `CircuitInfo`.
- Baseline scope becomes `unique_id`; friendly_name is display-only.
- Migration: on first boot after upgrade, existing scope=friendly
  rows are matched-once-then-rewritten to scope=unique_id (one-shot
  in the same restore loop, guarded by a schema/version key so it's
  idempotent).
- Non-SPAN "extra entities" (Emporia, Shelly): also have stable
  registry unique_ids — same treatment works.

Cost: single-cycle refactor in `energy_circuits.py` +
`energy.py::restore/save`. New QUALITY_CONTEXT bug class candidate:
"display-name used as persistence key across renameable upstream".

### B5. SPAN_REMAP_WORKSHEET status

Reading `docs/SPAN_REMAP_WORKSHEET.md`:

- The 5-room worksheet operates entirely inside URA's per-room
  Energy config (options flow REMOVE + ADD of entity_ids on
  sensor selectors). It is **unrelated** to the circuit-baseline
  scope key — that's a different subsystem persisted in the DB.
- Nothing in SPAN 2.0.x changes the worksheet's action set: the
  renamed circuit `Garage A EVSE` → `Car Charger` produces a new
  `entity_id`, which the room config must be pointed at.
- Item #5 (Game Room TV) still blocked on the TV integration, not
  SPAN.
- The worksheet's own "Not your problem" section already tags the 3
  orphaned DB baselines as "internal DB cleanup, handled in a future
  hygiene commit" — consistent with B3 above.

---

## Sources

- SpanPanel/span README + Releases:
  https://github.com/SpanPanel/span
  https://github.com/SpanPanel/span/releases
- span-panel-api: https://pypi.org/project/span-panel-api/
- SPAN API + Home On-premise beta announcement:
  https://www.span.io/blog/introducing-span-api-and-span-home-on-premise-public-beta
- SPAN privacy / policy 2026: https://www.span.io/privacy-2026
- HA unique_id guidance:
  https://developers.home-assistant.io/docs/core/integration-quality-scale/rules/entity-unique-id/
