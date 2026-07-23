# PLANNING — LKG-Envelope Adoption Wave 1 (D1 extract + D2 solar + D3 outdoor-temp)

**Status:** BUILD-READY. Follow-on to the SOC LKG + `SOCEnvelope` reference
implementation shipped in v5.28.0 (blind-window guard D5).
**Cycle trigger:** operator go 2026-07-23 on the top-3 ranked adoption from
`docs/planning/SURVEY_lkg_envelope_primitive_adoption.md`.
**Falsifiable invariant (the whole wave):** every consumer that reasons about
a signal's freshness routes through `LkgValue.envelope(now) -> (lo, hi, tier)`
and receives its freshness tier as a byproduct of asking for the envelope —
"is it stale?" is NEVER answered by a sibling inline predicate. Bug Class #53
(computed-but-not-consumed) is the failure mode the invariant blocks.

---

## Deliverables at a glance

| Del | Signal | Behavior | Tier | New decision paths? |
|-----|--------|----------|------|---------------------|
| D1  | SOC (refactor) | **BEHAVIOR-FROZEN** — extract `LkgValue` primitive; SOCEnvelope becomes a thin adapter. 122 test file + full guard matrix pass unmodified. | Tier 2-DB (money-path refactor; three framing-disjoint) | NO — byte-identical on the SOC path. |
| D2  | Solar production (live kW, `sensor.envoy_*_current_power_production` via `_battery.solar_production_w`) | **BEHAVIOR-ADDING** — persisted LKG + UPPER-envelope (physics: nameplate cap, decay toward Solcast-forecasted current rate). New consumer: excess-solar branch's `forecast_healthy` predicate + `determine_excess_solar_actions` upper-bound admit under Envoy blind window. | Tier 2-DB (money-path — excess-solar routing) | YES — see §D2 acceptance. |
| D3  | Outdoor temperature (WPM `current_apparent_temp`) | **BEHAVIOR-ADDING** — physics-bounded rate-of-change envelope during WPM `APPARENT_UNAVAILABLE` / all-providers-stale. Aligns with (does NOT duplicate) WPM's existing divergence machinery — the envelope is a NEW output of WPM, not a competing provider. | Tier 3 (cross-coordinator: WPM → HVAC preheat/precool + freeze-floor + covers + DPM) | YES — see §D3 acceptance. |

Rationale for the tier calls in §5.

---

## §1 — Context-wide blast-radius audit (operator gate)

### 1.1 D1 (SOC): every consumer of `SOCEnvelope` / `soc_envelope` / `get_lkg_snapshot` today

Full enumeration; each site is behavior-frozen (byte-identical output required):

- **Primitive site:**
  `energy_battery.py:68` `class SOCEnvelope` (pure math)
- **State fields:**
  `energy_battery.py:375-376` `_soc_lkg`, `_soc_lkg_at`
- **LKG writers:**
  `energy_battery.py:783-784` (primary read succeeds → cache)
  Test-only writes at `test_energy_battery.py` (~28 sites: 876, 2039, 2483, 2515, 2532, 2615, 2645, 2693, 2813, 2847, 2871, 2901, 2931, 2989, 3086, 3164 — all reset-to-None patterns);
  `test_cloud_reliance_d2.py:175` (aged staleness setup);
  `test_energy_write_verification.py:436-437` (soc-LKG-window fixture)
- **LKG readers / staleness gates:**
  `energy_battery.py:791-792` (resolver staleness fallback for `_get_soc_pct`)
  `energy_battery.py:1189-1193` (attribute emission fallback)
  `energy_battery.py:2096-2136` `soc_envelope()` — envelope construction site
- **Persistence surface (SQLite via `save_energy_state` — v5.28.0 shipped this, NOT the survey-recommended RestoreEntity path; see §6):**
  `energy_battery.py:2138-2149` `get_lkg_snapshot()`
  `energy_battery.py:2150-2172` `restore_lkg_snapshot()`
  `energy.py:1565-1576` restore call
  `energy.py:1911-1922` save call
- **Passthrough at EC layer:**
  `energy.py:3463-3468` `EnergyCoordinator.soc_envelope()`
- **Envelope consumers (decision sites):**
  `energy.py:3511` `blind_window_liveness_release` — envelope lower-bound gate
  `energy.py:3716` (second envelope consult — verify: liveness-release sister site)
  `energy.py:3760-3777` attrs `soc_envelope_lower/upper` — observability surface
  `energy_pool.py:640` `env = coord.soc_envelope()` — EVSE mid-charge admit
  `energy_pool.py:1426` second EVSE-pool consult
- **Tests hardening the SOC path (behavior-freeze harness):**
  `test_blind_window_evse_guard.py` (the 122-test file the operator called
  "the harness"; includes the C-HIGH-1 loud shim at :62-72 which asserts
  `SOCEnvelope.__module__ == "…energy_battery"` — **D1 will break this
  assertion when the class moves; the shim must migrate with the class
  as part of the freeze contract, not the behavior**).

**D1 refactor rule:** `SOCEnvelope` is REPLACED by a thin adapter over the
new generic `LkgValue`; ALL 6 primary + 4 test sites above are re-pointed;
the ~28 test-fixture writers keep the exact attribute names `_soc_lkg` /
`_soc_lkg_at` (they become properties over the new `LkgValue | None`).

### 1.2 D2 (solar production): every reader of solar production / forecast in EC

Grepped `solar_production`, `solar_production_w`, `_predicted_production_kwh`,
`current_rate_kw`, `remaining_forecast_kwh`, `forecast_healthy`,
`excess_solar_kwh_threshold`, `inclement_solar_horizon`.

- **Live solar (Envoy-sourced, goes None with SOC during blind window):**
  - `energy_battery.py:1470-1472` `solar_production` (kW property)
  - `energy_battery.py:1552-1560` `solar_production_w` (W convenience)
  - `energy_battery.py:3778, 4623, 5454, 5750` — attr emitters (observability; no decision)
  - `energy.py:2241` snapshot into signals dict (observability)
- **Predicted-daily (Solcast; independent of Envoy):**
  - `energy_forecast.py:97, 173, 231` `_predicted_production_kwh` (float | None)
  - `energy_forecast.py:91` basis string `'unavailable'`
- **`forecast_healthy` predicate (fill-priority / excess-solar entry):**
  - `energy_pool.py:2023-2036` `_fill_priority_solar_ok = forecast_healthy` (canonical)
  - `energy_pool.py:3309-3320` sibling site (v-N legacy path; verify still live before build)
  - `energy_pool.py:1978-2036` `determine_excess_solar_actions` — the excess-solar
    grant/release loop the operator flagged as blind-window-blind.
- **Attain / arbitrage ladder (uses Solcast + solar_production_w):**
  - `energy_battery.py:2477, 2530, 2626` `bound_to_solar_horizon=True` — attain
    scheduling. Reads Solcast day-forecast, NOT live solar production.
- **Inclement horizon** (`energy_battery.py:2066-2090` `inclement_solar_horizon`):
  reads solar decision structs, not live production.
- **DPM:** consumes forecast-apparent-high via WPM (see D3). Does NOT read
  solar production. **Not a D2 consumer.**

**D2 scope:**
- **Wire the envelope** into: `_battery.solar_production_w` (produce an
  `LkgValue`-backed cached-with-decay property `solar_production_w_envelope()`
  returning `(lo, hi, tier)`) AND route `forecast_healthy` at `energy_pool.py:2023`
  through it as documented in §D2.
- **Stay raw:** attain/arbitrage ladder (Solcast-driven, not Envoy-blind);
  observability attr emitters (no decision); `_predicted_production_kwh`
  (daily-cadence, different failure mode — belongs to the Solcast surface).
  Rationale per site: attain reads day-total forecast so live-solar staleness
  isn't its failure mode; observability MUST show None on stale (never a
  bounded value in the visible sensor state) so the operator can distinguish
  live from projected.
- **`_predicted_production_kwh` gets a DEGENERATE LKG** (identity bounds_fn,
  daily cadence): persist the last non-None value with `at`, expose as
  `LkgValue`, but decay is a step function at day-boundary (no physics
  intra-day). Scope-defer to Wave 2 unless review B finds it necessary
  for `forecast_healthy` when Solcast itself goes stale (currently binary None).

### 1.3 D3 (outdoor temp): every outdoor-temp consumer across coordinators

- **WPM (primitive owner):**
  `weather_manager.py:238-262` `current_apparent_temp() -> (val, age_s)` — the
  existing freshness-aware read. **Reuse.** D3 adds a sibling
  `current_apparent_temp_envelope() -> (lo, hi, tier)`.
  `weather_manager.py:264-291` `baseline_delta_for_zone` — reads `_cached_forecast.apparent_high`
  (day-forecast, not live). D3 does NOT change this path (different failure
  mode: day-forecast vs live).
- **HVAC preheat/precool (predictor):**
  `hvac_predict.py:1196-1206` `_get_outdoor_temp()` — direct entity read, does
  NOT go through WPM. Consumers at `:352-368` (predict-load buckets), `:645-658`
  (preheat gate). **Route through WPM's new envelope for graceful degradation.**
- **HVAC covers (solar-gain covers):**
  `hvac_covers.py:783-790` `_get_outdoor_temp()` — direct entity read. Consumers
  at `:438-463` (open/close decision on `_cover_close_temp` / `_cover_open_temp`).
  **Route through envelope.**
- **HVAC freeze-floor:**
  `hvac.py:1495-1511` `_get_best_outdoor_temp()` — currently delegates to predictor.
  Consumer: `_update_freeze_active` (:1513-1530), hysteresis-latched. **Route
  through envelope with a SAFETY-CONSERVATIVE reading rule** — freeze arm
  requires the envelope's UPPER bound ≤ trigger (worst-case cold), disarm
  requires LOWER bound > hysteresis (worst-case warm). See §D3.
- **DPM:** `dynamic_preset.py:525` reads `WPM.baseline_delta_for_zone` (day
  forecast, not live). Not directly affected by live envelope. HOWEVER: DPM
  overall depends on the WPM being healthy; the envelope BOOSTS DPM's
  resilience via WPM. **No code change in DPM; benefits transitively.**
- **Safety:** no direct outdoor-temp consumer found (grepped). Not in scope.
- **Sensor observability:** `sensor.py:7728` (WPM baseline emit). No change.

**D3 scope:** the four HVAC sites (predictor, covers, freeze-floor, best-outdoor
helper) all migrate to `WPM.current_apparent_temp_envelope()`. Freeze-floor
gets asymmetric-conservative reading rules. WPM becomes the sole owner of
outdoor-temp freshness math (align-don't-duplicate — the existing
`APPARENT_UNAVAILABLE` / `divergence_f` / `_last_probe_at` machinery is
retained; the envelope is a NEW derived output that sits alongside).

### 1.4 Cross-tier sweep summary

- Rooms tier: no outdoor-temp / solar / SOC consumers found. No blast radius.
- Zone tier: HVAC covers is per-zone via `hvac_covers.py`. Blast radius = 3
  cover controllers (from live config).
- House / coordinator tier: EC (D1, D2), HVAC (D3), WPM (D3), DPM (D3 transitive).
- Cross-cutting: signal bus untouched; no new signals emitted; no DB DDL.

---

## §2 — Institutional context verified

### Greps run + results

- **`LkgValue` — NEW.** No matches. This is the extraction target. Home:
  `custom_components/universal_room_automation/lkg.py` (NEW module).
- **`SOCEnvelope`, `soc_envelope`, `get_lkg_snapshot` — EXISTING** (shipped
  v5.28.0). D1 refactors these; enumerated above.
- **`solar_production_w`, `solar_production` — EXISTING**
  (`energy_battery.py:1470, 1552`). D2 adds a sibling `_envelope` accessor;
  keeps the raw properties for observability/back-compat.
- **`current_apparent_temp` — EXISTING** (`weather_manager.py:238`). D3 adds
  a sibling `_envelope` accessor on WPM.
- **`save_energy_state` / `restore_energy_state_with_age` — REUSED**
  (`database.py`, called from `energy.py:1565, 1917`). This is the URA-canonical
  LKG persistence path shipped in v5.28.0 for `battery_soc_lkg`. **D2 and D3
  persistence reuse the SAME DAO** — one key per signal: `solar_production_w_lkg`,
  `outdoor_apparent_temp_lkg`. See §6.
- **Numbers/config knobs — see §3.** All new bounds constants are module
  constants (rung 1), NOT config-flow / entity knobs.

### Prior planning docs consulted

- `docs/planning/SURVEY_lkg_envelope_primitive_adoption.md` — full read;
  §5 top-3 = this cycle's D1/D2/D3; §4 API sketch = D1's target shape.
- `docs/planning/PLANNING_ec_blind_window_evse_guard.md` — the cycle that
  landed `SOCEnvelope` + persistence. Read for the D5 shape.
- `docs/reviews/code-review/v5.28.0_ec_blind_window_guard.md` — verified the
  test-shim assertion pattern (C-HIGH-1) that D1 must preserve.
- `docs/planning/PLANNING_v4.7.x_dynamic_preset_management.md` — skimmed for
  DPM's dependence on WPM (transitive D3 benefit).

### Memory bodies pulled

- `project_envoy_boot_incident_2026_06_12.md` — Envoy freshness fragility.
- `project_inclement_arbitrage_wait_floor_gap.md` — Bug Class #53 (computed-
  but-not-consumed); the primitive-adoption failure mode this plan blocks by
  design (single `envelope()` call returns tier alongside bounds).
- `project_optimizer_db_write_flood_incident_2026_06_09.md` — write-cadence
  discipline; §6 enforces zero new DB writers.

### Design docs read

- `docs/Coordinator/ENERGY_COORDINATOR_MANUAL.md` §2.4b/2.5/2.6 (already read
  in the D5 cycle; excess-solar and blind-hold contracts are the surfaces
  D2 modifies).
- Weather / HVAC design docs — not present as `docs/Coordinator/<NAME>.md`
  files at time of writing; WPM's docstring (`weather_manager.py:1-15`) is
  the authoritative surface.

### Code locations surveyed end-to-end during scoping

- `energy_battery.py` :60-220 (SOCEnvelope + physics constants),
  :260-380 (BatteryStrategy init + LKG fields),
  :780-800 (LKG write + resolver staleness),
  :1180-1200 (attr emission),
  :1470-1560 (solar_production + solar_production_w),
  :2090-2175 (envelope + persistence helpers).
- `energy.py` :1550-1580 (restore call), :1900-1925 (save call),
  :3460-3550 (soc_envelope passthrough + liveness release),
  :3700-3800 (attrs emit).
- `energy_pool.py` :620-660 (EVSE envelope consult),
  :1400-1450 (second consult),
  :1975-2075 (`determine_excess_solar_actions` / `forecast_healthy`),
  :3290-3350 (sibling path).
- `weather_manager.py` :1-291 (full public API + probe + divergence).
- `hvac.py` :700-720, :1490-1560 (freeze-floor).
- `hvac_predict.py` :115-170, :350-370, :640-670, :1195-1210.
- `hvac_covers.py` :150-210, :325-470, :780-800.

---

## §3 — Per-signal `bounds_fn` design (with Numbers-Get-Knobs rung placement)

The generic primitive (see §4) takes a `bounds_fn: Callable[[val, at, now], (lo, hi, tier)]`
that is code-owned (NOT persisted; caller re-supplies on restore). Each
signal ships a physics factory alongside its coordinator's const module.

### 3.1 `soc_bounds` — SOC (D1, already shipped; extracted verbatim)

- **Physics constants (REUSED from `energy_const.py`):**
  `BATTERY_CAPACITY_KWH = 40.0` (:1462),
  `BATTERY_MAX_CHARGE_KW = 30.72` (:1463),
  `BATTERY_MAX_DISCHARGE_KW = 30.72` (:1464),
  `DEFAULT_SOC_LKG_ENVELOPE_MAX_AGE_S = 6 * 3600` (:1470).
- **Rung: 1 (module constant).** These are the shipped install's physical
  battery limits; changing them would require review AND a re-fit of
  the SOC envelope tests. Not operator-tunable knobs.
- **Bounds math (unchanged from `SOCEnvelope.compute`):**
  `lo = max(0, lkg - discharge_kw * age_s / (36 * capacity_kwh))`,
  `hi = min(100, lkg + charge_kw * age_s / (36 * capacity_kwh))`,
  clamp to `[0, 100]`, `tier = fresh (<60s) | lkg_bounded (<600s) | lkg_stale (<max) | expired (>max)`.

### 3.2 `solar_upper_bounds` — Solar production (D2, NEW)

- **Physics bound:** `production_w ∈ [0, SOLAR_NAMEPLATE_W]`.
  Live production CAN drop instantly (cloud edge) but CANNOT rise above
  installed inverter nameplate. Envelope is asymmetric:
  `lo = 0` (production can go to zero instantaneously),
  `hi = min(SOLAR_NAMEPLATE_W, upper_decay)` where `upper_decay` decays
  linearly from `lkg` toward the current Solcast-modelled expected rate over
  `SOLAR_LKG_UPPER_DECAY_S` (default 300s). Beyond that, `hi = current
  Solcast expected` (fresh Solcast) OR the nameplate (Solcast also stale).
- **New constant `SOLAR_NAMEPLATE_W`:**
  - **Value provenance:** the operator's installed Enphase inverter fleet
    nameplate (kW × 1000). This is a per-install physical constant.
  - **Placement:** `energy_const.py` **module constant** — rung 1.
    Rationale: the number changes only when the operator adds panels; that
    change SHOULD require code review because it invalidates the excess-solar
    threshold sanity too. NOT config-flow (not an operator-tunable comfort
    knob); NOT a Number entity (not turned by observation).
  - **Fallback default:** if unset, fall back to a defensive constant
    `SOLAR_NAMEPLATE_W_FALLBACK = 15_000` (15 kW — well above any single-family
    install, so upper-bound is never below reality — worst-case admits more
    excess-solar than physics but the SOC-envelope lower-bound guard downstream
    catches misfires). The fallback is loudly warned once on setup.
- **New constant `SOLAR_LKG_UPPER_DECAY_S = 300`:** module constant, rung 1.
  How fast the envelope's upper bound relaxes from LKG toward
  Solcast-expected. Chosen to match the D5 SOC envelope tier crossovers
  (`fresh <60s`, `lkg_bounded <600s`, `lkg_stale <max`).
- **`hard_max_age_s = 15 * 60`:** upper-bound envelope is useless past 15 min
  (a cloud front can invert production entirely). Beyond → `expired`.
- **Tier semantics (upper-only):** `fresh` (<60s live), `lkg_bounded` (<300s
  physics envelope), `lkg_stale` (300s ≤ age < 900s, admits only if
  `hi > excess_solar_kwh_threshold + safety_margin`), `expired` (fall back
  to current v5.28.0 behavior: binary None → excess-solar OFF).

### 3.3 `outdoor_temp_bounds` — outdoor apparent temperature (D3, NEW)

- **Physics bound:** rate of change of outdoor temperature.
  **Defensible number:** meteorological max sustained rate of change under
  extreme conditions (frontal passage, chinook) is on the order of 30°F/hr
  = 0.5°F/min. Steady-state diurnal rate is 5-10°F/hr. We use the extreme
  as the envelope width (worst-case honest, decisions still sound):
  `MAX_OUTDOOR_TEMP_DRIFT_F_PER_S = 30.0 / 3600 = ~0.00833`. Envelope:
  `lo = lkg - drift_rate * age_s`,
  `hi = lkg + drift_rate * age_s`,
  no hard clamp (temperatures can be any real).
- **New constant `MAX_OUTDOOR_TEMP_DRIFT_F_PER_HR = 30.0`:**
  - **Placement:** `energy_const.py` **module constant** — rung 1.
    (Or `weather_manager.py` — TBD in build; putting it beside the WPM
    consumer keeps physics next to consumer, but energy_const already
    owns the SOC physics constants, so a `weather_const.py` split is
    over-engineering.) Recommended: `energy_const.py` (reuses import path).
  - Rationale for rung 1: this is a defensible meteorological physical
    bound, not an operator preference. Changing it would require a
    counter-argument grounded in climatology. NOT a knob.
- **`hard_max_age_s = 6 * 3600`:** matches the D5 SOC envelope hard cap
  (`DEFAULT_SOC_LKG_ENVELOPE_MAX_AGE_S`). After 6h the envelope width
  is ±180°F — obviously useless. Tier crossovers:
  `fresh <300s` (WPM re-probes every ~5 min naturally),
  `lkg_bounded <1800s` (30 min — envelope width ±15°F, still actionable),
  `lkg_stale <max`, `expired > max`.
- **Freeze-floor asymmetric read (safety-conservative):** the freeze arm
  predicate reads `hi` (worst-case COLD is what would fail freeze open —
  actually wait: freeze arms on COLD → arm predicate uses `hi` (worst-case
  warm) ≤ trigger is TOO permissive; arm predicate must use `lo` (worst-case
  cold) ≤ trigger to AVOID unwanted arms, OR use `hi` ≤ trigger to be
  aggressive about arming. Correct safety posture: **freeze protection
  errs toward ARMED** — so arm when `lo ≤ trigger` (any-envelope reachable
  freeze), disarm only when `lo > trigger + hysteresis` (envelope proves
  cold impossible). This encodes the safety-conservative asymmetry the
  survey §2.3 flagged: envelope may PROLONG a hazard-side decision, never
  clear it prematurely.

---

## §4 — Primitive API (D1 extraction)

**File:** `custom_components/universal_room_automation/lkg.py` (NEW, ~180 LoC
including docstrings + tests helpers).

```python
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Literal, Optional

Tier = Literal["fresh", "lkg_bounded", "lkg_stale", "expired"]
BoundsFn = Callable[[float, datetime, datetime], tuple[float, float, Tier]]

@dataclass
class LkgValue:
    """Last-Known-Good value with a code-owned physics-bounded envelope.

    - `value` / `at` / `source` are persisted (attr or SQLite blob).
    - `bounds_fn` is NOT persisted — the coordinator supplies it on restore
      from its own constants module (soc_bounds, solar_upper_bounds,
      outdoor_temp_bounds live in energy_const alongside their physics).
    - Consumers ALWAYS call `envelope(now)` and receive `(lo, hi, tier)`
      in one call; there is NO separate `is_stale()` predicate. This kills
      Bug Class #53 by making the freshness tier a byproduct of the value read.
    """
    value: float
    at: datetime
    source: str
    bounds_fn: BoundsFn

    def envelope(self, now: datetime) -> tuple[float, float, Tier]:
        return self.bounds_fn(self.value, self.at, now)

    def to_blob(self) -> dict:
        return {"value": self.value, "at_iso": self.at.isoformat(),
                "source": self.source}

    @classmethod
    def from_blob(cls, blob: Optional[dict], bounds_fn: BoundsFn) -> Optional["LkgValue"]:
        # None-safe: None / malformed / tz-naive all return None cleanly.
        ...
```

**Physics factories:** `soc_bounds()`, `solar_upper_bounds()`,
`outdoor_temp_bounds()` — live in `energy_const.py` (SOC + solar) and
either `energy_const.py` or `weather_manager.py` (outdoor temp; recommended
`energy_const.py` for import-path uniformity).

**D1 refactor of `SOCEnvelope`:**
- Keep `class SOCEnvelope` as a shim at `energy_battery.py:68` that
  constructs a `bounds_fn` (via `soc_bounds()`) and exposes `.compute(lkg,
  age, max_age)` returning `(lo, hi)` — old API preserved verbatim so the
  test-file's 122 tests and all shim assertions pass. Internally, `.compute`
  builds a transient `LkgValue` and reads its envelope. `SOCEnvelope.__module__`
  stays `"...energy_battery"` — the loud shim at `test_blind_window_evse_guard.py:62-72`
  keeps working.
- `_soc_lkg` / `_soc_lkg_at` become **properties** over a private
  `_soc_lkg_obj: LkgValue | None` field. Setter path preserves the
  independent write of `_soc_lkg_at`. Test fixtures that do
  `h.strategy._soc_lkg = None; h.strategy._soc_lkg_at = None` still work.
- `get_lkg_snapshot()` / `restore_lkg_snapshot()` become thin adapters over
  `_soc_lkg_obj.to_blob()` / `LkgValue.from_blob(blob, soc_bounds(...))`.
  Persistence key (`"battery_soc_lkg"`) and blob shape (`{"value", "at_iso"}`)
  are UNCHANGED — the on-disk record survives the refactor byte-identical.

---

## §5 — Tier calls per deliverable

### D1 — Tier 2-DB (three framing-disjoint reviews + live)

- **Not Tier 3** because the invariant IS the byte-identical behavior of
  the SOC path, and the 122-test guard file + full excess-solar/EVSE
  matrix IS the falsifiable check: any drift falsifies at test time.
- **Framings (must be disjoint):**
  - A: correctness of the extracted primitive + the `SOCEnvelope` shim
    (arithmetic parity across all `age_s` regions, including boundary
    conditions on tier crossovers).
  - B: persistence + restore round-trip parity (blob shape unchanged,
    `save_energy_state` / `restore_energy_state_with_age` key unchanged,
    tz-aware/naive handling in `restore_lkg_snapshot` preserved, first-boot
    None-safe).
  - C: test-authority — every SOC consumer site (`energy_pool.py:640, 1426`,
    `energy.py:3511, 3716`, attr emitters) is exercised by at least one
    existing test; and the loud shim at `test_blind_window_evse_guard.py:62-72`
    still passes without modification. Per-site mutation: neuter `LkgValue.envelope`
    → the guard suite must go red at the SPECIFIC test that reads that consumer.

### D2 — Tier 2-DB (money path, single-signal migration)

- Solar-production envelope routes into `forecast_healthy` and
  `determine_excess_solar_actions` — this is the SAME excess-solar money
  path as v5.28.0's SOC guard. Getting the upper-bound wrong could either
  (a) admit a phantom-solar EVSE session under blind window (drain), or
  (b) refuse a real excess-solar session (opportunity cost).
- Framings:
  - A: envelope correctness for the upper-bound-only path + interaction
    with `excess_solar_kwh_threshold + safety_margin_kwh`.
  - B: money-path integrity — every `forecast_healthy` decision site
    (`energy_pool.py:2023-2036, 3309-3320`) reads the envelope tier and
    behaves identically at `expired` to today's binary-None path (fail-back
    is provably identical: guarantees no regression when Envoy is healthy).
  - C: test-authority — neuter the envelope at a single call site; a
    specific test must fail. Existing excess-solar tests are the harness.
- **Not Tier 3** because the falsifiable invariant is well-scoped: "under
  no Envoy blind window does the envelope-admit path admit an EVSE session
  the raw path would refuse." (Regression axis is one-directional; can be
  test-mutated.)

### D3 — Tier 3 (cross-coordinator; four framings including adversarial completeness)

- Delicate — the operator directive: aligning with WPM's divergence machinery
  without duplication, plus the freeze-floor asymmetric-conservative read
  (safety adjacent). Consumers span WPM → HVAC predictor → covers →
  freeze-floor → DPM(transitive), on independent config knobs
  (`_cover_open_temp`, `_cover_close_temp`, `FREEZE_TRIGGER_TEMP`,
  `FREEZE_TRIGGER_HYSTERESIS`), and asymmetric envelope reads.
- **Falsifiable invariant** (Tier-3 requires stating this upfront):
  *"Under any WPM state (all providers healthy | divergent | stale |
  APPARENT_UNAVAILABLE | all unavailable), for every outdoor-temp consumer,
  the safety-critical decision (freeze arm) can NEVER be silently cleared
  by a stale reading, AND the non-safety decisions (cover open/close,
  preheat threshold, precool bucket) either read a fresh point or a bounded
  envelope with tier ≥ `lkg_bounded`, NEVER a raw stale value AND NEVER
  fall back to raw entity read that races WPM's divergence flag."*
- Framings:
  - A: local correctness (per-site: envelope math, tier crossovers).
  - B: cross-coordinator integrity — no double-source (raw entity vs
    envelope) inside one decision; WPM divergence flag + envelope tier
    compose sanely; DPM's day-forecast path (unchanged) does not silently
    inherit stale-live-temp.
  - C: test-authority via per-site source mutation (neuter
    `WPM.current_apparent_temp_envelope` → each consumer's test fails at
    a NAMED test).
  - D: **adversarial completeness** — enumerate every outdoor-temp read
    site across the entire codebase (not just the diff), including pre-
    existing raw entity reads; assert every one either routes through
    the envelope or has a documented reason not to. Break the invariant
    with a legal-config repro (e.g. freeze trigger 32°F, hysteresis 6°F,
    WPM provider fails after LKG=33°F → does anything DISARM freeze in
    error?).

---

## §6 — Write-flood discipline

**Rule:** zero new DB writers introduced by this cycle beyond keys that
follow the existing `save_energy_state` cadence.

- **D1 (SOC):** unchanged. `save_energy_state("battery_soc_lkg", ...)` fires
  at the same cadence it fires today (once per persist-cycle in
  `energy.py:1911-1922`, part of the batched EC persist path). No new writer.
- **D2 (solar):** the envelope's `at` timestamp updates on every LIVE solar
  read tick (~30s). **Do NOT persist per-tick.** Persistence key
  `solar_production_w_lkg` piggybacks on the SAME EC persist path as
  `battery_soc_lkg` — one save per persist-cycle at most. In RAM the LKG
  updates every tick; SQLite only sees the periodic snapshot. This mirrors
  the D5-shipped shape exactly.
- **D3 (outdoor temp):** WPM already persists via `Store` (weather_manager
  `_apparent_high_store` at `weather_manager.py:155-157`). Reuse that same
  `Store` shape for the new envelope LKG (`ura_outdoor_temp_lkg` key), OR
  piggyback on the EC persist path with `save_energy_state("outdoor_apparent_temp_lkg", ...)`.
  **Recommendation:** EC persist path — consolidates LKG persistence in one
  place, matches D1/D2 cadence, avoids adding a new `Store` writer.
- **Survey vs shipped divergence — noted:** the SURVEY (§3) recommended
  RestoreEntity attr for tick-cadence LKGs; the SHIPPED v5.28.0 implementation
  used SQLite `save_energy_state` instead. This plan follows the SHIPPED
  precedent (SQLite via EC persist path) for cross-signal consistency. If
  a future Wave 2 splits back to attr, that is a separate cycle.
- **No new DDL.** All three keys use the pre-existing `energy_state`
  key-value store (`database.py`).

---

## §7 — Files touched (build manifest)

### D1 (behavior-frozen)
- **NEW:** `custom_components/universal_room_automation/lkg.py`
- **MODIFY:** `custom_components/universal_room_automation/domain_coordinators/energy_battery.py`
  (:68 SOCEnvelope shim, :375 fields → properties, :783 LKG write path,
  :791 resolver staleness read, :1189 attr fallback, :2096 envelope,
  :2138 snapshot, :2150 restore).
- **MODIFY:** `custom_components/universal_room_automation/domain_coordinators/energy_const.py`
  (add `soc_bounds()` factory next to the existing physics constants at :1462-1470).
- **UNCHANGED:** `energy.py` (persist/restore call sites), `energy_pool.py`
  (consumers). All continue to work through the preserved `soc_envelope()`
  passthrough at `energy.py:3463-3468`.
- **TESTS UNCHANGED:** `test_energy_battery.py` (28 `_soc_lkg` writer sites
  keep working via properties), `test_cloud_reliance_d2.py:175`,
  `test_energy_write_verification.py:436-437`, `test_blind_window_evse_guard.py`
  (122 tests + loud shim).
- **NEW TESTS:** `quality/tests/test_lkg_primitive.py` — bounds parity
  (SOCEnvelope.compute vs LkgValue.envelope over a 6h age grid), tier
  crossover, None-safe from_blob, tz-aware/naive restore, `SOCEnvelope.__module__`
  invariance.

### D2 (behavior-adding)
- **MODIFY:** `energy_battery.py` — add `solar_production_w_envelope() ->
  tuple[float, float, Tier] | None` next to `solar_production_w` at :1552;
  add `_solar_prod_lkg: LkgValue | None` field; write on live-read success
  at the same pattern as SOC LKG.
- **MODIFY:** `energy_const.py` — add `SOLAR_NAMEPLATE_W`,
  `SOLAR_NAMEPLATE_W_FALLBACK`, `SOLAR_LKG_UPPER_DECAY_S`,
  `DEFAULT_SOLAR_LKG_ENVELOPE_MAX_AGE_S`, `solar_upper_bounds()` factory.
- **MODIFY:** `energy.py` — add `EnergyCoordinator.solar_production_w_envelope()`
  passthrough; add persist/restore for `solar_production_w_lkg` next to the
  SOC LKG persist path at :1565 / :1911.
- **MODIFY:** `energy_pool.py` — route `forecast_healthy` at :2023-2036 through
  the envelope: admit under `(fresh | lkg_bounded)` with `hi ≥ excess_solar_kwh_threshold`,
  hold binary-None behavior at `expired`. Sibling site :3309-3320 gets the
  same treatment (verify still live at build time).
- **NEW TESTS:** `quality/tests/test_solar_envelope.py` — physics parity,
  envelope-admit under blind window, expired fall-through matches raw None.
- **UNCHANGED:** attain/arbitrage ladder sites (`bound_to_solar_horizon`),
  `_predicted_production_kwh` (Wave 2 candidate), observability attr emitters
  (must show raw None on stale so operator can distinguish live from projected).

### D3 (behavior-adding, cross-coordinator)
- **MODIFY:** `weather_manager.py` — add `current_apparent_temp_envelope() ->
  tuple[float, float, Tier] | None` at :262 (next to existing
  `current_apparent_temp`); add `_outdoor_temp_lkg: LkgValue | None` field;
  write on every healthy `current_apparent_temp` return; feed persist/restore
  via EC persist path (`outdoor_apparent_temp_lkg` key).
- **MODIFY:** `energy_const.py` — add `MAX_OUTDOOR_TEMP_DRIFT_F_PER_HR = 30.0`,
  `DEFAULT_OUTDOOR_TEMP_LKG_ENVELOPE_MAX_AGE_S = 6 * 3600`,
  `outdoor_temp_bounds()` factory.
- **MODIFY:** `hvac_predict.py:1196` `_get_outdoor_temp` — accept an
  optional `wpm` reference; when configured, prefer
  `wpm.current_apparent_temp_envelope()` returning `(lo+hi)/2` at
  `tier ≥ lkg_bounded`, else None. Wire `wpm` reference in `set_outdoor_temp_entity`
  or a new setter called from `hvac.py:702`.
- **MODIFY:** `hvac_covers.py:783` same treatment — cover open/close reads
  `(lo+hi)/2` at bounded tier.
- **MODIFY:** `hvac.py:1495` `_get_best_outdoor_temp` — asymmetric
  safety-conservative read for freeze-floor: arm predicate uses `lo`,
  disarm predicate uses `lo` too (envelope proves warm impossible). Explicit
  `_get_outdoor_temp_for_freeze_arm() / _for_freeze_disarm()` helpers so the
  code documents the asymmetry.
- **MODIFY:** `energy.py` — persist/restore `outdoor_apparent_temp_lkg` next
  to the SOC LKG persist path.
- **NEW TESTS:** `quality/tests/test_outdoor_temp_envelope.py` — envelope
  physics parity, WPM APPARENT_UNAVAILABLE fall-through, freeze-floor
  asymmetric arm/disarm invariant under stale WPM.

---

## §8 — Acceptance criteria (new behavior paths)

### D1 (byte-identical; the harness IS the acceptance)
- **Verify:** `git diff` against `pre-review-v<version>` shows behavior-only
  changes to `soc_envelope()`-adjacent code + the new `lkg.py` module.
- **Test:** the entire `test_blind_window_evse_guard.py` (122 tests) passes
  unmodified INCLUDING the loud shim assertion at :62-72.
- **Test:** all 28 `_soc_lkg = None` / `_soc_lkg_at = None` fixture sites in
  `test_energy_battery.py` continue to reset LKG state as before.
- **Test:** new `test_lkg_primitive.py` asserts `SOCEnvelope.compute()` output
  is bitwise-equal to `LkgValue(bounds_fn=soc_bounds(...)).envelope()` over a
  1000-point age grid `[0, 6h]`.
- **Live:** `sensor.ura_energy_coordinator_battery_strategy.soc_envelope_lower/upper`
  attrs continue to render as today (None when primary healthy; bounded
  values under Envoy stale). No boot-storm write flood.

### D2 (new behavior path: excess-solar admit under blind window)
- **Verify (unit):** with SOC LKG age = 120s AND live solar = None AND
  Solcast healthy AND `remaining_forecast_kwh >= excess_solar_kwh_threshold`,
  `forecast_healthy` returns True and `determine_excess_solar_actions`
  admits a candidate EVSE (previously refused for lack of live solar).
- **Verify (unit):** with solar LKG age = 20 min (> 15 min max envelope age),
  path collapses to binary-None (byte-identical to today's excess-solar OFF
  under blind window).
- **Verify (unit):** SOC envelope lower bound guard interaction — even when
  solar envelope admits, if `soc_envelope_lower < drain threshold` the
  liveness release refuses; regression matrix asserts no CRIT.
- **Sensor:** `sensor.ura_energy_coordinator_battery_strategy.solar_production_w_envelope_lower/upper/tier`
  new attrs render; `None` when primary live; `(lo, hi, tier)` under blind.
- **Live:** after a real (or synthesized) Envoy blind window with Solcast
  healthy and `remaining_forecast_kwh` above threshold, the EVSE receives
  an excess-solar grant; log line `"excess_solar admitted under envelope
  tier=lkg_bounded solar_hi=<W>"` appears once per grant.

### D3 (new behavior path: HVAC decisions ride WPM outage)
- **Verify (unit):** with all WPM providers unavailable but LKG apparent_temp
  age = 15 min AND `MAX_OUTDOOR_TEMP_DRIFT_F_PER_HR = 30`, envelope width
  is ±7.5°F; predictor's preheat gate at `hvac_predict.py:645-658` uses
  `(lo+hi)/2` and does NOT collapse to "no outdoor temp".
- **Verify (unit / safety-invariant):** freeze-arm invariant — for any
  `(LKG_temp, age)` combination such that `lo ≤ FREEZE_TRIGGER_TEMP`,
  freeze arms; and freeze NEVER disarms while `lo ≤ FREEZE_TRIGGER_TEMP +
  FREEZE_TRIGGER_HYSTERESIS`. This is the falsifiable invariant D reviews.
- **Verify (unit):** WPM divergence flag + envelope tier compose correctly;
  DIVERGENT + fresh returns raw + `tier=fresh` (existing divergence-driven
  decision paths unchanged).
- **Sensor:** WPM diagnostics sensor exposes
  `outdoor_apparent_temp_envelope_lower/upper/tier` attrs.
- **Live:** deliberately mark the primary weather entity unavailable in the
  live house (config-flow disable); confirm HVAC predictor continues to
  compute preheat/precool with a bounded envelope for ≥30 min before falling
  back to `expired`; confirm covers still open/close on the envelope
  midpoint; confirm freeze-floor does NOT flip active/inactive under any
  transient in that window.

---

## §9 — Open questions

1. **`SOLAR_NAMEPLATE_W` provenance.** Value is a per-install physical
   number. Does the operator have a canonical source in the config-flow
   already (grep found none), or do we hard-code the current fleet nameplate
   in `energy_const.py` with a comment pointing to the install docs? Recommend:
   hard-code as a module constant with a loud INFO log at setup so it's
   obvious in `home-assistant.log` what value is in play.
2. **`_predicted_production_kwh` degenerate LKG scope.** Wave 2 candidate,
   but if reviewer B finds `forecast_healthy` still races Solcast-stale
   under blind window, we may need it in D2. Deferred pending review.
3. **WPM persistence home.** SQLite EC-persist path (this plan's default)
   vs WPM's own `Store` (`weather_manager.py:155`). Recommendation: EC-persist
   for consistency with D1/D2; but if the reviewer flags cross-coordinator
   coupling smell, we split to WPM's Store.
4. **DPM transitive benefit — do we surface it explicitly?** DPM reads
   forecast-apparent-high (day cadence), NOT live temp; but DPM's other
   decisions (via WPM health) become more resilient. Recommend: no
   DPM code change; document the transitive benefit in the cycle README.
5. **Sibling `forecast_healthy` at `energy_pool.py:3309`.** Verify at build
   time whether this is a live path or dead code from an earlier refactor.
   If dead, remove; if live, migrate identically to :2023.

---

## Return summary

- **Blast-radius audit complete.** D1 = 6 primary sites + ~34 test sites
  (behavior-frozen). D2 = 2 canonical decision sites (excess-solar
  `forecast_healthy` × 2). D3 = 4 HVAC sites (predictor, covers, freeze,
  best-outdoor) + WPM primitive extension; DPM benefits transitively.
- **Bounds recommendations.**
  - SOC: reuse shipped constants (rung 1, module).
  - Solar: `SOLAR_NAMEPLATE_W` (rung 1, per-install physical), fallback 15 kW;
    `SOLAR_LKG_UPPER_DECAY_S = 300` (rung 1); asymmetric upper envelope
    with `lo = 0` (production drops instantly), `hi` decays toward Solcast.
  - Outdoor temp: `MAX_OUTDOOR_TEMP_DRIFT_F_PER_HR = 30.0` (rung 1,
    meteorological max chinook/frontal rate); symmetric envelope; freeze-floor
    reads asymmetric-conservative (arm on `lo ≤ trigger`, disarm on `lo >
    trigger + hysteresis`).
- **Tier calls.** D1 = Tier 2-DB (three framing-disjoint). D2 = Tier 2-DB.
  D3 = **Tier 3** (four framing-disjoint including adversarial completeness;
  cross-coordinator + safety-adjacent + asymmetric read semantics).
- **Persistence.** Zero new DB writers; three keys under the existing
  `save_energy_state` KV path piggyback on the EC persist cadence.

---
## Operator rulings — 2026-07-23 pre-build checkpoint
- **QUEUED BEHIND the owner-set registry cycle** (its persistence keys
  become registry declarations).
- **Solar upper bound: CONFIG-FLOW FIELD (rung 2), not a module constant.**
  Operator: array THEORETICAL max is **19.4 kW** — default the field to
  19400 W (not the ~15.4 kW observed peak; the envelope must bound what
  the array CAN do, not what it has done). Numbers-Get-Knobs entry updates
  accordingly.
