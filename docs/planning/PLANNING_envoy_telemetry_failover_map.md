# PLANNING — Envoy Telemetry Failover Map

**Cycle:** design (build-scoped D1-D3+D5; D4 optional-deferred)
**Filed:** 2026-07-13 (D5 folded in same day per operator addition)
**Author:** ura-planner (solo)
**Tier (proposed):** Tier 2-DB minimum. Elevate to Tier 3 IF D3
(battery_power / drain-gate) or D4 (degraded arbitrage) are accepted
for build — those routes touch the arbitrage / EVSE-pause / drain
invariant surface (`ura-energy-invariants-campaign` I-1..I-5).
**Related memories:** `project_dashboarding_workstream_2026_07_13.md`
(failover-map section), `project_ev_charge_start_deadband.md`
(v5.15.0 live proof interrupted by exactly the Envoy blip class this
cycle is meant to survive), `project_battery_soc_envoy_not_span.md`,
`project_envoy_boot_incident_2026_06_12.md`.
**Skills loaded:** `ura-energy-strategy-reference` §3, §10;
`ura-energy-invariants-campaign` Phase 0 / Phase 1.

---

## 0. Operator-pinned invariants — BINDING (verbatim)

State these verbatim in every review framing. They are the falsifiable
contract this cycle must satisfy.

1. **CONTROL surface = CLOUD PRIMARY, PERMANENTLY** (battery writes +
   command-state reads: reserve, mode, charge_from_grid — shipped
   v5.16.1 H1). NO failover mode may re-route control writes to the
   local leg. Local's control roles: secondary witness + explicit-blank
   demotion only.
2. **TELEMETRY surface = LOCAL PRIMARY** (SOC, power, production —
   fast, cloud-operator-resilient); cloud = SUSTAINED-failure fallback.
3. **Debounced trip, hysteretic return**: local blips constantly
   (HA / Envoy / transient network); trip only on consecutive missed
   polls over minutes (mirror the SOC resolver's LKG tier,
   `energy_battery.py` ~L596-655, and the cfg blip-latch philosophy);
   fail back with hysteresis.
4. **Falsifiable master invariant (I-F1):** "No single `unavailable`
   read may change any consumer's data source." A reviewer must be
   able to falsify this with one poll-miss synthetic and see the pair
   NOT flip.
5. **(Operator addition 2026-07-13) Auditability + continuous
   validation:** the auto-built pair map must be 100% inspectable
   on demand AND continuously cross-validated in-flight. Missing
   pairs, WRONG pairs, and silent drift are all reviewable events.

Derived invariants for the reviewer to falsify (Phase 0 format):

| ID | Invariant | Falsified by |
|---|---|---|
| I-F1 | Single `unavailable` read never flips a pair's `source`. | Any pair whose `source` differs at tick N vs N-1 given exactly ONE missed local poll at N. |
| I-F2 | CONTROL write routing byte-identical before/after this cycle in all failover states. `write_verify.py` command paths unchanged. | Any diff to a write route in `energy_write_verify.py` or `_get_cloud_for_control` (`energy_battery.py:556-578`). |
| I-F3 | Return hysteresis strictly exceeds trip hysteresis: `RETURN_CONSECUTIVE_OK > TRIP_CONSECUTIVE_MISS`. No flap under any missed-poll pattern. | A synthetic alternating 5×miss/1×ok/5×miss/1×ok that flips source. |
| I-F4 | Pair whose measured p95 staleness exceeds a consumer's `max_stale_s` MUST NOT serve that consumer, even when both legs are "available." | A pair with lag > gate serving `battery_power` to the drain-gate. |
| I-F5 | Sign + unit preserved 1:1 across failover. `_normalize_percent` (energy_write_verify.py:50) is the ONLY unit normalizer on the read path. | Any cloud→consumer path that skips the unit guard. |
| I-F6 | Deterministic map: identical entity-registry inputs produce identical `map_hash` across cold boots. Any real change produces exactly one INFO log line naming `old_hash`, `new_hash`, `trigger_reason`. | Two boots against unchanged registry that produce different `map_hash`, or a real change that logs at DEBUG only. |
| I-F7 | A pair flagged `mismatch=true` (D5.3) that then trips MUST fall to `source="none"` NOT `source="cloud"`. WRONG pairings never serve consumer reads under fallback. | A test that forces mismatch + trip and observes `source="cloud"`. |

---

## 1. Institutional context verified — MANDATORY

Per `CLAUDE.md` §Institutional Context First.

### 1.1 REUSED — DO NOT reinvent

| Primitive | file:line | Reuse how |
|---|---|---|
| Three-tier SOC resolver (primary → LKG ≤300s → cloud fallback) | `energy_battery.py:611-689` | Cycle GENERALIZES to N pairs. No new SOC path. |
| `DEFAULT_SOC_LKG_MAX_AGE_S = 300` | `energy_const.py:219` | Default per-pair `lkg_max_age_s`; overridable per pair from measured p95. |
| `DEFAULT_CLOUD_BATTERY_SOC_FALLBACK_ENTITY` | `energy_const.py:213` | Existing SOC pair anchor. |
| Cloud oracle map + coherent-blank demotion | `energy_battery.py:_get_cloud_for_control` L546-578 | CONTROL surface. Untouched. |
| `envoy_available` LOCAL health probe | `energy_battery.py:1384-1409` | Base "local leg alive?" per pair. |
| `_envoy_degraded` / `_envoy_degraded_since` | `energy.py:582-583, 2037-2054` | Coarse degraded flag. Cycle adds per-pair granularity beneath. |
| `_check_soc_source_divergence` | `energy_battery.py:690-...` | Pattern for per-pair witness compare / staleness measurement. |
| `_normalize_percent` unit guard | `energy_write_verify.py:50` | The ONLY unit normalizer on any cloud-read path (I-F5). |
| `_witness_compare` (v5.16.1 H1) | `energy_write_verify.py:656-...` | Reference impl of the compare/log pattern. |
| `soc_source_last` attr precedent | `energy_battery.py:626, 665, 668, 674, 676` | Per-pair `<pair>_source` attribute surface. |
| Envoy cache save/restore | `energy.py:1353, 1384` | Cross-restart LKG durability pattern (SOC only for now). |
| `_get_state_float/_str/_bool` | `energy_battery.py:580-608` | All local + cloud reads. |
| `battery_power_w` sign convention | `energy_battery.py:814-833` | Sign preservation across failover (D3). |
| `AnomalyDiagnosticDumpButton` (dump-to-disk precedent) | `button.py:1177-1229` (unique_id `<domain>_anomaly_diagnostic_dump`) | Blueprint for D5.1 `TelemetryMapDumpButton`. |
| Existing anomaly subsystem (type discriminator, DAO, dedup window) | AnomalyType/anomaly_type shipped v4.7.12 | D5.3 emits `telemetry_pair_mismatch` through this — no new channel. |

### 1.2 NEW — justified

| Proposal | Justification |
|---|---|
| `class TelemetryPair` + `PairState(source, lkg_at, consecutive_miss, consecutive_ok, measured_p95_s, mismatch)` | SOC resolver hard-codes ONE pair. Nothing iterates a pair set. N>1 needs a registry with per-pair debounce + mismatch state. |
| Per-pair debounce constants: `TRIP_CONSECUTIVE_MISS=3`, `RETURN_CONSECUTIVE_OK=5`, `LOCAL_POLL_INTERVAL_S=60` | SOC resolver uses wall-clock LKG age, not consecutive-miss. Operator directive requires "consecutive missed polls over minutes." Wall-clock age can trip on ONE miss → violates I-F1. |
| `sensor.ura_energy_telemetry_failover` | Nothing aggregates per-pair source today; scalar `soc_source_last` is inadequate. Dashboard cycle + reviewer both need this. |
| Per-pair `staleness_measured_p95_s` — rolling estimator | Operator: "measured freshness, not assumed." No existing estimator per pair. |
| Consumer classification table (explicit `pair_key, max_stale_s, accept_cloud` per site) | ONLY way I-F4 becomes reviewable is if every consumer's tolerance is declared, not implicit. |
| **D5:** `diagnostics.py` (HA diagnostics platform), `TelemetryMapDumpButton`, cross-validator, `map_hash` + registry-event rebuild | Auto-build failure modes = (a) missing pair, (b) WRONG pair (unit/serial mismatch), (c) silent drift on registry change. Boot log + coverage sensor summary are necessary but not sufficient. Diagnostics gives full download; continuous validation catches (b); deterministic hash + rebuild-on-event catch (c). |

### 1.3 NOT proposed — deliberately excluded

- **NO config-flow surface** (operator directive). Pair map built
  invisibly from the two config entries.
- **NO changes to `_get_cloud_for_control`** or any control-write
  route (invariant #1, I-F2).
- **NO changes to `_result` clamp / `_floor_reserve`.** Cycle does
  not touch reserve emission; energy-invariants Phase 4 applies only
  if D4 ships.
- **NO new anomaly channel.** D5.3 reuses the shipped anomaly
  subsystem and dedup window.

### 1.4 Prior planning + memory bodies consulted

- Memory: `project_dashboarding_workstream_2026_07_13.md` (failover-map
  section — this cycle IS that entry).
- Memory: `project_ev_charge_start_deadband.md` — v5.15.0 L3 live proof
  was **interrupted** 2026-07-12 by exactly the Envoy blip class this
  cycle targets (`SOC None → drain release fail-safe held on
  garage_a`). This cycle would have kept the drain release evaluable.
- Memory: `project_battery_soc_envoy_not_span.md` — Envoy SOC
  canonical; SPAN `battery_level` miscalibrated. MUST NOT accidentally
  re-introduce SPAN as fallback.
- Memory: `project_envoy_boot_incident_2026_06_12.md` — boot-time
  Envoy failures + RestoreEntity `unavailable→OFF` poisoning
  (Bug Class #52). Debounce trip must NOT count boot-window
  `unknown/unavailable` reads; guard via `envoy_available` gate + boot
  grace (mirror v4.7.21 boot-storm settle gates).
- Design doc: `docs/Coordinator/ENERGY_COORDINATOR_DESIGN_v2.3.md` §1.
- Skill: `ura-energy-strategy-reference` §3 (priority #1 = Envoy
  unavailable → hold), §10 (trust hierarchy).
- Skill: `ura-energy-invariants-campaign` Phase 0/1.

### 1.5 Code locations surveyed end-to-end during scoping

- `energy_battery.py` L546-708 (control cloud map, three-tier SOC
  resolver, divergence check)
- `energy_battery.py` L1384-1409 (envoy_available LOCAL probe)
- `energy_battery.py` L798-833 (battery_power / battery_power_w sign)
- `energy.py` L577-583, L2037-2054, L3282, L6755 (envoy_degraded state)
- `energy_const.py` L196-219 (cloud oracle CONFs + SOC LKG constant)
- `energy_write_verify.py` L50 (unit normalizer), L656 (witness compare)
- `button.py` L1177-1229 (AnomalyDiagnosticDumpButton dump-precedent
  for D5.1)

### 1.6 Pair enumeration — REQUIRED before build (B0)

Run on host `ha` per `ura-diagnostics`; capture output as appendix:

```bash
ssh ha "python3 -c 'import json; \
  reg=json.load(open(\"/config/.storage/core.entity_registry\")); \
  entries={\"01KNYRAGVP5XESS6N8PD6BVQP2\":\"envoy_local\", \
           \"01KR1YNV6PKXMSZSXY42PVGJ25\":\"enphase_ev_cloud\"}; \
  out=[(e[\"entity_id\"],entries.get(e[\"config_entry_id\"],\"\"),e.get(\"unique_id\")) \
       for e in reg[\"data\"][\"entities\"] \
       if e[\"config_entry_id\"] in entries]; \
  print(\"\\n\".join(f\"{tag}\\t{eid}\\t{uid}\" for eid,tag,uid in sorted(out)))'"
```

Cross-reference against
`/Users/okosisi/ha-config/custom_components/enphase_ev/` for the
canonical unique_id / entity-name convention (device serial + class).
B0 output is what the pair-builder consumes in D1.

---

## 2. Executive summary (8-10 lines)

Generalize the shipped 3-tier SOC resolver into an N-pair telemetry
failover map covering every Envoy telemetry read (SOC, power,
production, storage-mode-for-read). Local↔cloud pairs are built at
startup from the two integration config entries (envoy_local
01KNYRAGVP5XESS6N8PD6BVQP2, enphase_ev cloud
01KR1YNV6PKXMSZSXY42PVGJ25) by serial + entity-class match — **NO
config surface**. Each pair carries a consecutive-miss debounce
counter (trip default 3 over ~3 min) and a hysteretic return gate
(`RETURN_CONSECUTIVE_OK > TRIP_CONSECUTIVE_MISS`) — a single blip
cannot flip a consumer; a marginal link cannot flap. Per-pair
empirical staleness is measured (rolling p95 lag) and consumers gate
on **measured** freshness, not assumed 5-min. CONTROL writes and
command-state reads are UNTOUCHED (v5.16.1 H1). Consumer
classification is explicit: SOC accepts fallback; `battery_power`
(drain-gate — sign+latency critical) does NOT; production accepts
with widened margins. **D5 makes the map fully auditable**: HA
diagnostics-platform JSON download + optional dump button (precedent
`button.py:1177`), a coverage sensor with `pairs_total`,
`unpaired_local[]`, `unpaired_cloud[]`, `map_hash`, `last_built`,
continuous per-pair value+unit cross-validation (persistent
divergence → `telemetry_pair_mismatch` anomaly — catches WRONG
pairings not just missing), unit guard at pair-build time,
deterministic content-hash + rebuild-on-registry-event with an INFO
log per change (no silent drift). Optional D4 designs a
cloud-corroborated degraded arbitrage mode with wider SOC margins as
a separately-gated deliverable.

---

## 3. Deliverables

### D1 — Invisible pair-map builder + `TelemetryPair` primitive

**Scope.** New module `domain_coordinators/telemetry_failover.py`. At
`EnergyCoordinator.__init__` (or `async_setup`), enumerate entities
from both config entries via
`entity_registry.async_entries_for_config_entry`, group by device
serial, class-match into pairs. NO config-flow field.

```python
@dataclass
class PairState:
    source: str  # "local" | "lkg" | "cloud" | "none"
    lkg_value: float | str | None
    lkg_at: datetime | None
    consecutive_miss: int
    consecutive_ok: int
    measured_p95_lag_s: float | None
    last_local_val: Any | None
    last_cloud_val: Any | None
    mismatch: bool                # D5.3
    mismatch_reason: str | None   # D5.3

class TelemetryPair:
    key: str                    # "battery_soc", "battery_power", ...
    local_entity: str | None
    cloud_entity: str | None
    kind: Literal["percent", "power_w", "energy_wh", "enum"]
    max_stale_s_for_consumers: dict[str, float]
    match_rationale: str        # D5.1 — reviewer-visible pair reason
    def read(self) -> tuple[Any, str]: ...
```

Boot grace: for the first `BOOT_GRACE_S = 120` s after coordinator
ready, `unavailable` reads DO NOT increment `consecutive_miss`
(Bug Class #52 defense; mirrors v4.7.21 boot-storm settle gates).

The existing SOC pair MUST be byte-identical to
`energy_battery.py:611-689` behavior on the happy path — regression
test target.

**Acceptance Criteria — D1**
- **Verify:** Pair map built at boot; log line
  `Telemetry failover map built: <N> pairs (soc, power, production,
  storage_mode_read) hash=<map_hash>`.
- **Verify:** Zero config-flow additions — grep
  `config_flow.py`/`options_flow.py` diff for new fields returns nil.
- **Sensor:** `sensor.ura_energy_telemetry_failover` state = pair
  count; per-pair attrs
  `{source, consecutive_miss, consecutive_ok, measured_p95_lag_s,
    local_entity, cloud_entity, mismatch}` (per-pair block via a
  compact nested attribute; large-fields off-loaded to diagnostics —
  see D5.2).
- **Test:** `test_telemetry_pair_map_built_from_config_entries` —
  fake registry with both entry IDs, assert expected pairs exist.
- **Test:** `test_soc_resolver_byte_identical_on_happy_path` — same
  envoy value via generic path and legacy `battery_soc` property;
  assert identical value + `source == "local"`.
- **Live:** After deploy, sensor attributes list at least the SOC pair
  with `local_entity=sensor.envoy_*_battery`, `source=local`.

### D2 — Debounced trip + hysteretic return (I-F1, I-F3)

**Scope.** Consecutive-miss counter increments only on
`unavailable`/`unknown` **outside** the boot grace. Trip when
`consecutive_miss >= TRIP_CONSECUTIVE_MISS` (default 3; ~3 min at 60 s
poll). Return when `consecutive_ok >= RETURN_CONSECUTIVE_OK`
(default 5) with `RETURN_CONSECUTIVE_OK > TRIP_CONSECUTIVE_MISS`.

Per-pair source ordering when local is TRIPPED:
1. `lkg` if `now - lkg_at <= lkg_max_age_s` (default reuse
   `DEFAULT_SOC_LKG_MAX_AGE_S = 300`).
2. `cloud` if `pair.cloud_entity is not None` AND unit/range guards
   pass AND pair is NOT `mismatch=true` (I-F7 — a mismatched pair
   falls straight to `none`, never cloud).
3. `none` — read returns None; consumer decides.

`_normalize_percent` guards the cloud read on any `kind == "percent"`
pair (I-F5).

**Acceptance Criteria — D2**
- **Verify (I-F1):** One synthetic unavailable read after a stable
  window MUST NOT flip source. Pytest:
  `test_single_blip_never_flips`.
- **Verify (I-F3):** 5×miss / 1×ok / 5×miss / 1×ok pattern MUST NOT
  flap source. Pytest: `test_return_hysteresis_prevents_flap`.
- **Verify (boot):** During first 120 s post-boot, 5 consecutive
  unavailable reads MUST NOT trip. Pytest:
  `test_boot_grace_suppresses_trip`.
- **Live:** Trigger by disabling the local Envoy SOC entity for
  ~5 min (`ha_call_service homeassistant.disable_entity`). Observe
  `consecutive_miss` climb → `source` flip to `lkg` then `cloud`. On
  re-enable, observe `consecutive_ok` climb → `source` returns to
  `local` only after 5 OK ticks.

### D3 — Consumer classification + measured freshness gate (I-F4)

Every telemetry consumer declares `(pair_key, max_stale_s,
accept_cloud)`:

| Consumer | pair | max_stale_s | accept_cloud | Rationale |
|---|---|---:|---|---|
| `battery_soc` property (strategy math) | `battery_soc` | 300 | YES | Reuse of shipped 3-tier behavior. |
| Drain-gate ±100 W discharge check (`energy_pool.py` ~L994) | `battery_power` | 90 | **NO** | Sign + latency critical; cloud lag likely exceeds 90 s; wrong-sign risk. Falls to "hold current pause state" NOT "release." |
| Excess-solar / fill-priority (`energy.py` ~L307, `energy_pool.py:692`) | `solar_production` | 600 | YES, with widened threshold (`+2 kWh` margin) | Slow-varying; stale reading tolerable if it WIDENS the gate not narrows. |
| `envoy_available` (strategy priority #1) | `battery_soc` (anchor) + `storage_mode_read` LOCAL | n/a | **NO** | This IS the local health probe; must stay LOCAL-only (see `energy_battery.py:1392-1401` fix-up A-HIGH-1). |

Drain-gate is the load-bearing I-F4 case: if `battery_power`'s
measured p95 lag > 90 s the gate MUST NOT release the pause; it holds
current state (fail-safe = same as sensor-dead today).

**Acceptance Criteria — D3**
- **Verify:** Grep `energy_pool.py`, `energy_battery.py`, `energy.py`
  produces a table where every telemetry read routes through the pair
  registry OR is documented as excluded.
- **Test:** `test_drain_gate_refuses_cloud_fallback`.
- **Test:** `test_solar_gate_widens_on_cloud`.
- **Test:** `test_measured_p95_gates_reads` — set pair
  `measured_p95_lag_s = 200`; consumer with `max_stale_s=90` gets
  `None` even when both legs are "available."
- **Live:** During a real Envoy blip, `garage_a` drain-gate behavior
  does NOT change source. No NM "sensor-dead" false alarm.

### D4 — OPTIONAL: cloud-corroborated degraded arbitrage

**Status:** designed-not-built by default. Operator accepts/defers at
Phase-6 checkpoint. If accepted → **Tier 3** (touches
`_arbitrage_pre_conditions`, `_get_arbitrage_decision`, reserve
emission surface — invariants campaign I-1..I-5 apply in full).

**Current behavior (baseline, W-3 mutation-anchored):**
`envoy_available == False` → priority-1 short-circuit → strategy
holds; no commands (`energy_battery.py:3230`). Arbitrage deactivated.

**Proposed degraded mode.** When local trips but cloud SOC is fresh
(`measured_p95_lag_s ≤ 300`):
- Widen `peak_buffer_target` down by `-10 %` (conservative
  under-shoot).
- Widen `partial_hold_reserve_floor` up by `+10 %` (conservative
  over-hold).
- Refuse to start a NEW arbitrage CHARGE chunk; complete only
  in-flight chunks.
- `_floor_reserve` still enforced on every emit (I-1 unchanged).

**Acceptance Criteria — D4 (if accepted)**
- **Invariant proof:** Full Phase 4 mutation matrix (every emit site
  gets its own FAIL-on-neuter test) covers the degraded-mode branch.
- **Verify:** Grep `reserve_level=` diff — every NEW/CHANGED site
  routes through `_floor_reserve`.
- **Test:** `test_degraded_arbitrage_no_new_chunks`.
- **Test:** `test_degraded_arbitrage_widens_symmetrically`.
- **Live:** N/A until natural degraded window occurs.

### D5 — Auditable + continuously-validated pairing map (operator addition)

Motivation: auto-build failure modes are (a) MISSING pair (caught by
D5.2 `unpaired_*` lists), (b) *WRONG* pair (two entities matched that
don't actually correspond — worst case: consumers silently routed to
wrong data), (c) silent drift on registry change (rename / new
device). D1's boot log alone is insufficient evidence.

#### D5.1 — On-demand full-map export

- **HA diagnostics platform.** New
  `custom_components/universal_room_automation/diagnostics.py`
  implementing `async_get_config_entry_diagnostics(hass, entry)` per
  HA developer docs.
  Payload MUST include: `pairs[]` (each with `key`, `local_entity`,
  `cloud_entity`, `local_unique_id`, `cloud_unique_id`, `serial`,
  `kind`, `unit_of_measurement_local`, `unit_of_measurement_cloud`,
  `match_rationale`, `measured_p95_lag_s`, `source`,
  `consecutive_miss`, `consecutive_ok`, `mismatch`,
  `mismatch_reason`), `unpaired_local[]` (each with `reject_reason`
  if applicable), `unpaired_cloud[]`, `map_hash`, `built_at`,
  `rebuild_count`, `rebuild_reason` (last), `boot_grace_active` (bool).
  `match_rationale` is short + structured, e.g.
  `"serial=482543015950,class=battery_soc,unit=%"`.
- **Dump-to-disk button** following `button.py:1177-1229`
  (`AnomalyDiagnosticDumpButton`, unique_id
  `<domain>_anomaly_diagnostic_dump`) precedent. New:
  `button.ura_energy_coordinator_telemetry_map_dump` → writes
  timestamped JSON to
  `/config/universal_room_automation/data/telemetry_map_dumps/<ISO>.json`.
  Same shape as diagnostics payload. Persists for post-incident review.

#### D5.2 — Live coverage sensor (attrs only, no full map)

Full map exceeds HA state-attribute size budgets. Diagnostics carries
full; `sensor.ura_energy_telemetry_failover` SUMMARIZES.

Attrs on `sensor.ura_energy_telemetry_failover` (state = pair count):

| Attr | Type | Meaning |
|---|---|---|
| `pairs_total` | int | Number of paired entities |
| `unpaired_local` | list[str] | Local envoy entities with no cloud match |
| `unpaired_cloud` | list[str] | Cloud enphase_ev entities with no local match |
| `map_hash` | str | `sha1(canonical-json(pair-set))[:8]` |
| `last_built` | ISO ts | Last (re)build time |
| `rebuild_count` | int | Total rebuilds since boot |
| `pair_mismatch_count` | int | Pairs currently in mismatch state (D5.3) |
| `boot_grace_active` | bool | True during first 120 s post-ready |

Total attr JSON size < 4 KB (HA soft-cap sanity).

#### D5.3 — CONTINUOUS cross-validation (catches WRONG pairings)

Each decision tick (5 min), for each pair where BOTH legs have a
fresh available value in a rolling window:

1. **Unit sanity.** `unit_of_measurement_local ==
   unit_of_measurement_cloud` after `_normalize_percent` (or
   explicitly normalized by pair `kind`). Any unresolvable mismatch →
   pair `mismatch=true, mismatch_reason="unit_mismatch"`.
2. **Value tolerance.** Per-pair tolerance:
   - `kind == "percent"` → ±3 pp
   - `kind == "power_w"` → ±150 W absolute OR ±10 %, whichever larger
   - `kind == "energy_wh"` → ±5 %
   - `kind == "enum"` → exact match under normalization
   Compare last local sample to cloud sample from
   `now - measured_p95_lag_s ± window` (pattern mirrors
   `_check_soc_source_divergence` `energy_battery.py:690-...`).
3. **Persistent divergence.** Exceeded tolerance for
   `PAIR_MISMATCH_CONSECUTIVE = 3` sampling windows → emit ONE
   anomaly via the existing anomaly subsystem (type
   `telemetry_pair_mismatch`, severity `medium`), fields:
   `pair_key`, `local_entity`, `cloud_entity`, `observed_local`,
   `observed_cloud`, `tolerance`,
   `mismatch_reason ∈ {"unit_mismatch", "value_divergence", "sign_divergence"}`.
   Debounced by existing anomaly dedup — one anomaly per sustained
   event.
4. **Unit enforcement AT PAIR TIME (D1).** Pair builder REJECTS
   candidates whose units disagree after normalization. Rejected
   entities show in `unpaired_*` with `reject_reason` on the
   diagnostics payload (not the summary sensor).

Consumer behavior on mismatch (I-F7): pair continues serving `local`
(higher-trust leg per invariant #2) but is marked `mismatch=true`. A
pair in `mismatch` that then trips (D2) falls straight to `none` —
NEVER cloud.

#### D5.4 — Deterministic + versioned map (no silent drift)

- **Determinism.** Pair builder consumes
  `(sorted local entity_registry rows for entry L, sorted cloud rows
  for entry C, class-match rules)` → canonical-sorted pair list.
  `map_hash = sha1(canonical-json(pairs))[:8]`. Same inputs → same
  hash every boot.
- **Rebuild triggers.** Subscribe to
  `homeassistant.helpers.entity_registry.async_track_entity_registry_updated_event`
  (HA dev docs — verify signature before use; do NOT invent) for
  entities belonging to either config entry. Debounced coalesce
  (5 s window) to survive rename bursts.
- **Change logging.** Every rebuild logs at INFO with fields
  `old_hash`, `new_hash`,
  `trigger_reason ∈ {"boot", "entity_registry_added",
  "entity_registry_updated", "entity_registry_removed", "manual"}`,
  `pairs_added`, `pairs_removed`, `pairs_hash_changed`. If `old_hash
  == new_hash` → log at DEBUG (no-op rebuild).
- **Manual rebuild service.**
  `universal_room_automation.rebuild_telemetry_map` (no args). Reuse
  existing `hass.services.async_register` plumbing in `__init__.py`.

**Acceptance Criteria — D5**
- **Verify (D5.1 diagnostics):** From HA UI *Settings → Devices &
  Services → URA → 3-dots → Download diagnostics* produces a JSON.
  `jq '.pairs | length'` equals the coverage sensor `pairs_total` at
  the same instant.
- **Verify (D5.1 dump button):** Pressing
  `button.ura_energy_coordinator_telemetry_map_dump` writes a file
  under `/config/universal_room_automation/data/telemetry_map_dumps/`;
  content identical shape to diagnostics payload.
- **Sensor (D5.2):** All attrs from the D5.2 table present; total
  JSON < 4 KB.
- **Verify (D5.3 unit mismatch at pair time):** Inject a synthetic
  cloud entity with unit `"W"` where the local mate is `"%"`. Assert
  the candidate is REJECTED at pair-build, appears in
  `unpaired_cloud` with `reject_reason="unit_mismatch"` in
  diagnostics, and produces NO runtime anomaly.
- **Verify (D5.3 runtime divergence):** Force local SOC=70, cloud
  SOC=50 for 3 consecutive windows; assert exactly ONE
  `telemetry_pair_mismatch` anomaly, pair `mismatch=true`; a
  subsequent trip results in `source="none"` NOT `source="cloud"`
  (I-F7).
- **Verify (I-F6 determinism):** Two cold boots against an unchanged
  registry produce identical `map_hash`.
- **Verify (D5.4 rebuild on rename):** Rename a cloud entity via HA
  UI (or `entity_registry.async_update_entity`); within 60 s observe
  (a) INFO log `old_hash != new_hash` with `trigger_reason`, (b)
  `map_hash` on the coverage sensor changes, (c) `rebuild_count`
  increments by 1.
- **Verify (log discipline):** Zero-change reload logs at DEBUG,
  never INFO. No boot-time INFO storm on setup retries.
- **Test:** `test_pair_builder_deterministic_hash`,
  `test_pair_builder_rejects_unit_mismatch`,
  `test_pair_mismatch_anomaly_debounced`,
  `test_mismatched_pair_falls_to_none_on_trip` (I-F7),
  `test_map_rebuild_on_registry_event`,
  `test_map_rebuild_debounced_on_burst`,
  `test_diagnostics_payload_shape`,
  `test_registry_listener_unsubscribed_on_unload` (Bug Class #19/#50).
- **Live:** After deploy: download diagnostics → pair count matches
  coverage sensor; deliberately rename `sensor.envoy_*_battery` via
  the HA UI → within 60 s coverage sensor `map_hash` changes and
  `rebuild_count` increments; rename back → hash returns to original.

---

## 4. Files touched

| File | D1 | D2 | D3 | D4 (opt) | D5 | Nature |
|---|---|---|---|---|---|---|
| `domain_coordinators/telemetry_failover.py` | NEW | NEW | ext | ext | ext | New module (est. 400-550 LoC incl. D5 cross-validator + registry-event listener) |
| `custom_components/universal_room_automation/diagnostics.py` | — | — | — | — | NEW | HA diagnostics platform (D5.1) |
| `domain_coordinators/energy.py` | ext | ext | ext | ext | ext | Wire pair-map at setup; consumer sites in solar/drain gates; wire registry-event listener |
| `domain_coordinators/energy_battery.py` | keep | keep | ext | ext | — | `battery_soc` property re-routes through pair (byte-identical); D4 arbitrage widen |
| `domain_coordinators/energy_pool.py` | — | — | ext | — | — | Drain-gate + excess-solar consumer wiring |
| `domain_coordinators/energy_const.py` | ext | ext | — | ext | ext | Debounce constants + per-kind tolerance constants + `PAIR_MISMATCH_CONSECUTIVE` |
| `sensor.py` | ext | ext | — | — | ext | `EnergyTelemetryFailoverSensor` + D5.2 attrs |
| `button.py` | — | — | — | — | ext | New `TelemetryMapDumpButton` following L1177 precedent |
| `__init__.py` | — | — | — | — | ext | Register `rebuild_telemetry_map` service |
| `quality/tests/test_telemetry_failover.py` | NEW | NEW | NEW | opt | ext | All D1-D5 test cases |
| `docs/QUALITY_CONTEXT.md` | — | — | — | — | ext | Anomaly `telemetry_pair_mismatch` documented; candidate Bug Class #54 "unmeasured freshness assumption" (see §7) |

---

## 5. Constants (D1/D2/D5)

Add to `energy_const.py`:

```python
# Telemetry failover map — debounce constants
# I-F1: single unavailable read never flips a pair.
# I-F3: RETURN > TRIP so a marginal link cannot flap.
DEFAULT_TELEMETRY_TRIP_CONSECUTIVE_MISS: Final = 3
DEFAULT_TELEMETRY_RETURN_CONSECUTIVE_OK: Final = 5
DEFAULT_TELEMETRY_BOOT_GRACE_S: Final = 120

# Reused: DEFAULT_SOC_LKG_MAX_AGE_S = 300 already covers per-pair LKG.

# Per-consumer max_stale_s presets (D3 table)
TELEMETRY_MAX_STALE_S_BATTERY_POWER_DRAIN_GATE: Final = 90
TELEMETRY_MAX_STALE_S_SOLAR_PRODUCTION: Final = 600

# D5.3 continuous cross-validation
PAIR_MISMATCH_CONSECUTIVE: Final = 3
PAIR_TOLERANCE_PERCENT_PP: Final = 3.0
PAIR_TOLERANCE_POWER_W_ABS: Final = 150.0
PAIR_TOLERANCE_POWER_W_REL: Final = 0.10
PAIR_TOLERANCE_ENERGY_WH_REL: Final = 0.05

# D5.4 registry-event rebuild debounce
TELEMETRY_MAP_REBUILD_DEBOUNCE_S: Final = 5.0
```

No CONF_* additions (operator directive: no config surface).

---

## 6. Review protocol

**Default: Tier 2-DB** (three framing-disjoint reviews + live).

**Elevate to Tier 3 IF D3 (drain-gate) OR D4 (arbitrage) is built** —
project CLAUDE.md standing policy for shared-primitive changes.

Framings:
- **A — local correctness.** Debounce arithmetic; pair-builder set
  membership; unit guard on cloud reads; hash canonicalization
  (unordered dict → equal hash); tolerance-table arithmetic. State
  I-F1..I-F7 as truth tables.
- **B — integration / state-machine integrity + restart resilience.**
  Boot grace does not swallow real failures; existing SOC pair
  byte-identical on happy path (regression); `envoy_available` still
  ONLY reflects LOCAL leg; CONTROL writes byte-identical (I-F2); the
  registry-event listener unsubscribes on unload (Bug Class #19/#50 —
  untracked-listener regression class); rebuild debounce coalesces
  bursts without dropping a real change; anomaly emit uses existing
  dedup window (no new channel).
- **C — test authority via per-site source mutation.** For each D3
  consumer, neuter the pair-registry call at that ONE site (replace
  with raw local read) and confirm a SPECIFIC test fails. For D5.3,
  neuter the unit check → assert
  `test_pair_builder_rejects_unit_mismatch` fails; neuter the
  consecutive-mismatch counter → assert
  `test_pair_mismatch_anomaly_debounced` fails.
  Aggregate monkeypatch NOT sufficient
  (`ura-energy-invariants-campaign` Phase 4).
- **D (Tier 3 only, if elevated) — adversarial completeness.**
  Enumerate every `hass.states.get("sensor.envoy_*")` or
  `_get_state_float` on an envoy-family entity in
  `domain_coordinators/` — including pre-existing code, not just the
  diff. Also enumerate every subscription/unsub in
  `telemetry_failover.py` (registry listener is a new lifecycle
  owner) and every anomaly-emit site (must reuse channel). Any
  missed site is a leak.

**Pre-review baseline tag:**
```
git tag pre-review-vX.Y.Z -m "Pre-review baseline"
```

**Orchestrator independent verification before ship:**
1. Re-run pair-builder grep against the entity registry; count
   matches the plan.
2. Re-run one source mutation on the drain-gate consumer and one on
   the D5.3 unit-check; confirm `≥1 failed` each.
3. Verify no diff in `_get_cloud_for_control` and no new field in
   `config_flow.py`/`options_flow.py` (I-F2 + operator directive).
4. Compute `map_hash` from two cold boot logs; assert equal (I-F6).

---

## 7. Verification steps (post-deploy)

Write results back into `README_v<version>.md` per CLAUDE.md Live
Validation write-back rule.

1. `ha_get_state` `sensor.ura_energy_telemetry_failover` — state = pair
   count; attrs from D5.2 table populated.
2. `ha_get_state` `sensor.envoy_*_battery` — pair's `source == "local"`
   in steady state.
3. Trigger simulated blip (disable local SOC entity via
   `ha_call_service homeassistant.disable_entity` for
   `TRIP_CONSECUTIVE_MISS + 1` cycles) → observe:
   - `consecutive_miss` climbs monotonically.
   - `source` transitions `local → lkg → cloud`.
   - `envoy_available` on battery-strategy sensor STILL reflects LOCAL
     health (invariant #1 preservation).
   - Drain-gate on `switch.garage_a` does NOT release (I-F4 in live).
4. Re-enable → `consecutive_ok` climbs → source returns `local` after
   exactly `RETURN_CONSECUTIVE_OK` OK ticks.
5. Download diagnostics from HA UI: `jq '.pairs | length'` equals
   coverage sensor `pairs_total`.
6. Rename `sensor.envoy_*_battery` via HA UI (reversible) → within
   60 s observe INFO log with `old_hash != new_hash`, `map_hash`
   attr changes, `rebuild_count` increments. Rename back → hash
   returns.
7. Steady state: zero `telemetry_pair_mismatch` anomalies.
8. No WARNING bursts in URA logs from fluctuation (single `INFO
   source flip` per transition is expected).
9. Bug-Class-#53 spot-check: `reserve_level` attr on battery-strategy
   sensor unchanged in shape (D1-D3+D5 do NOT touch reserve emits).

### Candidate new Bug Class (proposal for QUALITY_CONTEXT.md)

**#54 — Unmeasured Freshness Assumption.** A consumer treats a
telemetry read as fresh because it is "available" (not
`unavailable`/`unknown`) without checking how OLD the underlying
value is. Endemic on cloud-backed entities that keep serving the last
uploaded sample for minutes. Detection: any `_get_state_float` on a
cloud entity where the caller acts on sign/latency-critical semantics
without a lag gate.

---

## 8. Open operator questions (undecidable only)

1. **D4 (degraded arbitrage): accept, defer, or reject?** The
   conservative baseline (arbitrage OFF while local Envoy dead) is
   correct and mutation-anchored. D4 recovers some arbitrage utility
   during sustained-local-out windows at Tier-3 cost. Not deciding is
   fine — cycle can ship D1-D3+D5.
2. **Debounce constants — accept defaults or pin per-pair to measured
   cadence?** Defaults (`TRIP=3`, `RETURN=5`, `BOOT_GRACE=120s`,
   `LKG=300s`) assume 60 s local poll → trip at ~3 min, return at
   ~5 min. If B0 pair enumeration reveals a pair with 5-min native
   cadence, `TRIP=3` at 60 s tick means a real 15-min outage before
   trip on that pair. Options: (a) accept, (b) pin per-pair `TRIP` to
   `max(3, ceil(180s / pair_poll_s))`. Recommend (b); operator call
   because (a) is simpler.
3. **Live blip simulation authorization.** Verification step #3
   requires disabling `sensor.envoy_*_battery` for ~5 min against
   the live house. Operator OK / prefer natural blip / prefer
   LAN-unplug instead? Recommend service disable (reversible, no
   network impact).
4. **Does the enphase_ev HACS integration expose a stable
   `battery_power` cloud analogue?** B0 pair enumeration will answer
   empirically. If NO, D3 drain-gate simply has no cloud fallback and
   the classification becomes "local-only, hold on trip" — still
   correct, just narrower. Not blocking for build.
