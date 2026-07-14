# AUDIT — Manual Envoy Local↔Cloud Telemetry Pairing

**Filed:** 2026-07-13 (evening, live values sampled ~21:40 CDT / 02:40 UTC)
**Purpose:** Hand-build the local↔cloud pair map ONCE, before the failover-map
cycle's auto-builder does it a thousand times. This document is the **oracle**
the runtime auto-builder and its cross-validator (D5) are audited against.
Every verdict below was made against LIVE values, not name similarity.
**Method:** (1) enumerate every Envoy/Enpower entity URA consumes
(`energy_const.py:136-139` control defaults + `:727-739` auto-derived
telemetry set); (2) dump the full entity registries of `enphase_envoy`
(local, 858 entities) and `enphase_ev` (cloud HACS, ~190 entities);
(3) hand-match candidates; (4) pull live state+unit+state_class for every
candidate pair and compare values, units, signs, and epochs.

---

## 1. Control surface (cloud-primary since v5.16.1 — for completeness)

| URA role | Local entity | Cloud entity | Verdict | Notes |
|---|---|---|---|---|
| Storage mode | `select.enpower_482348004678_storage_mode` | `select.iq_gateway_hacs_system_profile` | **PAIRED (shipped)** | Label map `STORAGE_MODE_LOCAL_TO_CLOUD` (energy_const.py:222). |
| Reserve SOC | `number.enpower_482348004678_reserve_battery_level` [%] | `number.iq_battery_hacs_battery_reserve` | **PAIRED (shipped)** | ⚠ Cloud number carries **no unit metadata** in the registry (blank vs local `%`). Values are percent; auto-builder must not reject on missing unit. |
| Charge from grid | `switch.enpower_482348004678_charge_from_grid` | `switch.iq_battery_hacs_charge_battery_from_grid` | **PAIRED (shipped)** | Live tonight: local `on` vs cloud `off` — the known local-lie divergence; cloud is authoritative. |
| Grid enable/disable | `switch.enpower_482348004678_grid_enabled` | — | **NO ANALOGUE (GAP)** | Cloud exposes grid toggle only via OTP flow (`button.iq_gateway_hacs_request_grid_toggle_otp`), not a switch. If local write path is dead for this too (untested), URA has **no working grid-disconnect control**. Not exercised by any current URA codepath beyond reads — verify before ever relying on it. |

## 2. Telemetry surface (local-primary; cloud = sustained-failure fallback)

Live sample columns are from the same minute (~21:40 CDT) unless noted.
Cloud updated 21:40:41; local 21:40:49.

| # | URA input (CONF_*) | Local entity [unit] · live | Cloud candidate [unit] · live | Verdict | Notes / required transform |
|---|---|---|---|---|---|
| T1 | BATTERY_SOC | `sensor.envoy_..._battery` [%] · 30 | `sensor.iq_battery_hacs_battery_overall_charge` [%] · 31.5 | **PAIRED (shipped v5.16.1 fallback)** | 1.5 pp divergence, inside the 3 % threshold. The one pair already production-proven. |
| T2 | SOLAR (production power) | `sensor.envoy_..._current_power_production` [kW] · 0.0 | `sensor.enphase_cloud_hacs_current_production_power` [W] · 0 | **PAIRED — ×1000 transform** | Unit factor W→kW. Trivially safe at night; re-confirm midday. |
| T3 | BATTERY_POWER | `sensor.envoy_..._current_battery_discharge` [kW] · 0.01 | `sensor.enphase_cloud_hacs_current_battery_power` [W] · 2007 | **CANDIDATE — sign UNVERIFIED, values diverged at sample** | Local ~0 vs cloud 2.0 kW at the same minute (lag or boundary difference). Local name implies discharge-positive; cloud name implies signed. **Do not pair until sign convention is proven with a paired observation during a known charge AND a known discharge.** This is the drain-gate/EVSE input (D3) — highest stakes pair in the map. |
| T4 | NET_POWER (grid) | `sensor.envoy_..._current_net_power_consumption` [kW] · 6.428 | `sensor.enphase_cloud_hacs_current_grid_power` [W] · 67 | **SEMANTIC MISMATCH — do not pair blindly** | At the same minute local reports 6.4 kW grid import; cloud reports 67 W. ~6 kW of the local import is (very likely) the off_peak EV charge — and the cloud integration exposes `site_evse_charging` separately, so its "grid power" plausibly **excludes the EVSE circuit** (or tells a lagged, different-boundary story). A naive pairing here would have the failover feed the strategy a number ~100× off. Must be resolved with a controlled observation (EVSE on vs off) before this pair is admitted. |
| T5 | CONSUMPTION (house power) | `sensor.envoy_..._current_power_consumption` [kW] · 6.713 | — | **NO 1:1 ANALOGUE** | Cloud has no instantaneous consumption power. Derivable as production + grid ± battery only AFTER T3/T4 semantics are settled. Recommend: `source=none` on local failure (LKG then blank). |
| T6 | BATTERY_CAPACITY | `sensor.envoy_..._battery_capacity` [Wh] · 40000 | (`sensor.iq_battery_hacs_battery_available_energy` [kWh] · 12.6) | **NO ANALOGUE (derived only)** | Cloud entity is *available* energy, not capacity: 12.6 / 40.0 = 31.5 % = cloud SOC exactly. Capacity is a constant — LKG/persisted value suffices forever; no cloud pair needed. |
| T7 | CONSUMPTION_TODAY | `sensor.envoy_..._energy_consumption_today` [kWh] · **0.0 at 21:40 CDT** | `sensor.enphase_cloud_hacs_site_consumption` [kWh] · 56 762 | **MISMATCH both ways** | Two independent findings: (a) the local "today" counter had just reset — **Envoy day-counters roll at UTC midnight** (02:40 UTC sample = 0.0), not local midnight; any URA consumer assuming local-midnight semantics is already subtly wrong. (b) The cloud sensor is a lifetime-style site total, not "today". **No valid pair.** |
| T8 | LIFETIME_PRODUCTION | `..._lifetime_energy_production` [MWh] · 9.82 | `..._site_solar_production` [kWh] · 44 445 | **EPOCH MISMATCH — delta-only pair** | Both are lifetime `total_increasing`, but different epochs: cloud counts since site commissioning (44.4 MWh), local since this Envoy's baseline (9.8 MWh). Absolute values must NEVER substitute; only *deltas over a window* are exchangeable. Same verdict for T9–T12. |
| T9 | LIFETIME_CONSUMPTION | `..._lifetime_energy_consumption` [MWh] · 14.30 | `..._site_consumption` [kWh] · 56 762 | **EPOCH MISMATCH — delta-only** | |
| T10 | LIFETIME_NET_IMPORT | `..._lifetime_net_energy_consumption` [MWh] · 5.89 | `..._site_grid_import` [kWh] · 21 456 | **EPOCH MISMATCH — delta-only** | |
| T11 | LIFETIME_NET_EXPORT | `..._lifetime_net_energy_production` [MWh] · 1.41 | `..._site_grid_export` [kWh] · 6 634 | **EPOCH MISMATCH — delta-only** | |
| T12 | LIFETIME_BATT_CHARGED / _DISCHARGED | `..._lifetime_battery_energy_charged` [MWh] · 3.29 / `..._discharged` · 2.64 | `..._site_battery_charge` [kWh] · 12 902 / `..._site_battery_discharge` · 10 809 | **EPOCH MISMATCH — delta-only** | Also MWh↔kWh factor. |

## 2b. Units & sign conventions per pair — the transform contract

URA-internal canonical conventions (verified in code, not assumed):

- **Battery power:** URA canonical = **positive = charging, negative =
  discharging**, in **W**. The local entity is discharge-positive, so URA
  flips the sign on read (`energy_battery.py:811` raw, `:832`
  `battery_power_w` with kW→W scaling). Any cloud substitute must be
  transformed INTO this convention, not into the local entity's.
- **Net/grid power:** URA canonical = **positive = importing** (it reads the
  local *net consumption* entity as-is; `energy_battery.py:790-795`, unit-safe
  variant `net_power_w` via `_read_power_w` `:886`).
- **Unit normalization precedent:** `_read_power_w` / `battery_power_w`
  already auto-scale kW→W by inspecting `unit_of_measurement` — the map's
  general normalizer should extend THIS pattern (and `_normalize_percent`
  for %), not introduce a third.

| Quantity | Local unit · sign (VERIFIED) | Cloud unit · sign | Transform cloud→URA-canonical | Status |
|---|---|---|---|---|
| Battery SOC | % · n/a | % · n/a | identity | ✅ verified (30 vs 31.5 live) |
| Reserve SOC | % · n/a | *(blank metadata)* · n/a | identity; do not require unit equality | ✅ value-verified (30 ↔ 30.0) |
| Production power | kW · always ≥0 | W · always ≥0 (assumed) | ÷1000→kW or ×1 in W-canon; ≥0 assert | ⚠ factor verified at 0/0 only — re-verify midday nonzero |
| Battery power | kW · **discharge-positive** (URA flips to charge-positive W) | W · sign convention **UNKNOWN** (2007 W observed while battery likely discharging → *suggests* discharge-positive, single sample) | ×(±1)·scale — **blocked on sign proof** | ❌ requires paired obs: one known charge, one known discharge |
| Net/grid power | kW · **import-positive** | W · sign convention UNKNOWN + suspected EVSE-circuit exclusion (F1) | undefined until semantics settled | ❌ blocked (worst pair, see T4) |
| House consumption power | kW · ≥0 | — | n/a | no analogue |
| Lifetime energies | MWh · monotonic | kWh · monotonic, different epoch | ×1000 + epoch offset; **delta-only** | ⚠ delta-mode only |
| Today energy | kWh · resets **UTC midnight** | — (site total, not today) | n/a | no analogue + F4 |

Auto-builder admission rule derived from this table: a pair is admissible
only when (unit factor) AND (sign map) AND (epoch/boundary semantics) are
all three explicitly known — name + device_class similarity alone admits
nothing. T3/T4's row status is exactly what the cross-validator must be
able to output at runtime.

## 3. Health / meta pairs (the probes themselves)

| Role | Local | Cloud | Verdict |
|---|---|---|---|
| Leg health | `envoy_available` probe (energy_battery.py:1384) | `binary_sensor.enphase_cloud_hacs_cloud_reachable` · on | **PAIRED** — each leg has its own health signal; the map's trip logic should consume both. |
| Freshness | local entity `last_updated` | `sensor.enphase_cloud_last_successful_update` (timestamp) + `sensor.enphase_cloud_cloud_latency` [ms] · 1134 | **PAIRED** — cloud integration self-reports poll success + latency; feed the per-pair p95 estimator from these, don't re-derive. |

## 4. Findings (ranked)

1. **F1 — T4 net/grid power is the WRONG-pair landmine.** Same-minute
   readings disagree by ~100× (6.4 kW vs 67 W).
   *(Revised 2026-07-13 late, after operator correction + B0 follow-ups.)*
   The initial EVSE-exclusion hypothesis is **dead** — the operator has no
   Enphase EVSE; the Emporia EVSE hangs off SPAN and is undifferentiated
   load to the Enphase consumption CT. Follow-up measurement eliminated
   every other benign explanation: no sign flip, no algebraic identity
   (net, −net, net±battery, cons−prod, |net| — all ≥2.6 kW p50 off), no
   time-averaging window (5/15/30/60-min trailing averages all leave a
   ~2 kW p50 residual), no lag (0-30 min swept). The distributions differ
   in kind: cloud median ~0.07 kW vs local 2.9 kW, cloud max 38.8 kW vs
   local 16.6 kW (physically implausible) — consistent with the HACS
   integration deriving "grid power" from misaligned interval-energy
   deltas rather than a CT reading. Candidate upstream bug worth reporting
   to the `enphase_ev` project. Verdict NEVER ADMIT is final. This single
   finding justifies the whole manual audit and the I-F7 fail-to-`none`
   invariant: an auto-builder pairing by name+device_class+unit would have
   admitted it.
2. **F2 — T3 battery power sign convention unverified** (discharge-positive
   local vs signed cloud unknown) and values diverged at sample. D3 must not
   ship until a two-condition paired observation (known charge, known
   discharge) pins the sign map.
3. **F3 — every lifetime pair is epoch-mismatched** (site-lifetime vs
   Envoy-lifetime). The auto-builder must classify these as *delta-only*
   pairs or exclude them; the cross-validator's compare must be on windowed
   deltas, never absolutes.
4. **F4 — local "today" counters roll at UTC midnight** (observed 0.0 at
   21:40 CDT). Independent of failover: any URA consumer of
   `*_today` assuming local-midnight is already wrong by 5 h. Worth a
   follow-up grep of consumers.
5. **F5 — unit factor is ×1000 (W↔kW) on every instantaneous power pair**,
   and MWh↔kWh (×1000) on lifetime pairs. `_normalize_percent` covers only
   %; the map needs a general unit normalizer (extends I-F5).
6. **F6 — cloud reserve number has blank unit metadata**; the builder must
   not require unit equality for admission (device_class + value-range
   corroboration instead).
7. **F7 — no cloud analogue exists for:** house consumption power (T5),
   battery capacity (T6, constant — LKG suffices), grid_enabled control
   (§1 gap, OTP-only in cloud), and "today" energy (T7).
8. **F8 — cloud endpoint cadences differ per family** (production stamped
   21:32, grid/battery 21:40 in the same poll cycle) — confirms the
   operator's measure-don't-assume directive; freshness must be per-pair.

## 5. Verdict summary for the auto-builder

| Class | Pairs |
|---|---|
| Admit (with ×1000 transform where noted) | T1, T2; health/meta pair |
| Admit only after controlled observation | T3 (sign proof), T4 (EVSE-exclusion proof) |
| Delta-only mode or exclude | T8–T12 |
| Never admit (no analogue) | T5, T6, T7, grid_enabled |

## 6. Phase B0 probe — first run (2026-07-13 ~21:55 CDT, 48h window)

One-shot read-only recorder analysis (`scripts/telemetry_pair_probe.py`,
run on the HA host over SSH; exits after ~seconds, nothing resident).
Diffs are in local units (kW / %) at the best-fit lag on a 60s step-hold grid.

| Pair | Local cadence p50/p95 | Cloud cadence p50/p95 | Best lag | diff p50 / p95 | B0 verdict |
|---|---|---|---|---|---|
| battery_soc | 162s / 899s | 621s / 2180s | 0s | 0.5 pp / 4.9 pp | **ADMIT** — outage-grade substitute |
| production_power | 72s / 156s | **916s / 1302s** | 0s | 0.07 kW / 7.2 kW | **ADMIT for slow consumers only** (day-class, trend); p95 blows up during ramps at ~15-min staleness — never for instantaneous math |
| battery_power | 72s / 198s | 314s / 932s | 0s | 0.55 kW / 6.6 kW | **Sign RESOLVED**: as-is beats sign-flipped (p95 6.6 vs 19.4 kW) → cloud is discharge-positive like the local entity; apply the same flip URA already does. But divergence p95 6.6 kW ⇒ **D3 (drain-gate feed) REJECTED by measurement** — blind-hold is safer than 5-15-min-stale power |
| net_power | 70s / 98s | 314s / 932s | 120s | **2.74 kW / 12.5 kW** | **NEVER ADMIT** — p50 divergence of 2.7 kW at best lag proves this is a semantic mismatch (suspected EVSE-circuit exclusion, F1), not a polling delay. No lag correction can fix it. |

Cadence takeaway: the cloud HACS *polls* every ~62s but its power values
refresh only every ~5-15 min upstream (Enlighten granularity). The gap is
data freshness, not poll rate — polling harder cannot close it.

**Build-scope consequence:** D3 and D4 fall out of scope on measured
grounds; the failover map ships SOC (+ production for slow consumers) with
per-consumer staleness gates, plus the auditability substrate. Re-run the
probe after ~a week (one command, covers sunny/cloudy days + EV sessions)
as the final pre-build gate; the T4/net-power EVSE-exclusion hypothesis can
also be confirmed then by comparing divergence during vs outside EV
charging windows.

The runtime cross-validator (D5.3) must be able to *re-derive every verdict
in §2 on its own*: unit-factor detection (F5), epoch-offset detection (F3),
and same-minute magnitude divergence (F1) are its three mandatory checks.
This table is the acceptance fixture: run the builder, diff its map against
§5, and every disagreement is either a builder bug or a documented
improvement to this audit.
