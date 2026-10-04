# DRAFT README — EC degraded-data policy, Phase 1 (5.103.x)

Card: EC-DEGRADED-DATA-POLICY-1 (absorbs EC-ATTAIN-HOLD-WHEN-ENVOY-BLIND-1).
Plan: `docs/planning/PLANNING_ec_degraded_data_phase1.md` (Tier 3; plan reviews #1 and #2 binding; §12 operator
rulings 2026-10-04). Branch `feature/ec-degraded-data-p1`. Draft: version number assigned at deploy.

## What changes (plain)

When the Envoy integration drops out, URA used to keep acting on whatever battery reading it could find, including
the Enphase cloud number, which has been wrong in both directions (frozen at 10% for two hours on 10-02; reading
96.2% while the battery was at 90% on 10-03). Phase 1 makes URA careful when its battery reading is not trustworthy:

1. **No car-charging release on missing data (D2a).** If cars were paused by the battery-charging logic, URA keeps
   them paused while the battery reading is untrusted (cloud only, or nothing). After 60 minutes of continuous
   untrusted readings it lets them go only if the grid-charge switch is provably off.
2. **"Unknown" is not "off" (D2b).** If the grid-charge switch stops reporting and URA's own last command turned it
   on, URA treats it as on and keeps cars paused (breaker protection). A manual "off" seen on the switch is believed
   and cancels that memory. If this goes on for 10 minutes overnight with a car held, URA pages you.
3. **Should-start-by, not must (D2c, operator ruling).** The morning car-charge deadline now waits behind breaker
   protection and every other protective hold. When a start is held past its deadline URA logs it, sends a
   notification and writes an anomaly row (`ev_must_start_by_held`).
4. **Cloud never the only reason to grid-charge (D3).** On a tick where the only battery reading is the cloud one,
   URA does not command charging from the grid; a running grid charge is stood down (cars stay paused). Storm
   pre-charging is exempt (operator Q2). The reason line says
   "(grid charge withheld: cloud-only battery reading)".
5. **Page before a rate change (D4).** If the battery reading has been untrusted for 10+ minutes within 90 minutes of
   a higher-rate period, URA sends one high-priority notification for that period. It also fires in observation
   mode (it is advice, not an action).
6. **New attributes on the battery strategy sensor (D5):** `soc_tier_trusted`, `stream_trust`
   (`trusted`/`quarantined`/`disabled`), `grid_charge_withheld_untrusted`, `arb_release_refused`.
7. **Local stream battery reading (D1) — shipped switched OFF.** A new tier that uses the local MQTT stream
   (`sensor.envoy_stream_battery_soc`) when the Envoy drops out. Code constant `SOC_STREAM_TIER_ENABLED = False`
   until the stream A/B readout (ENVOY-STREAM-AB-48H-1, 2026-10-05 13:05 CDT) says GO. Two new optional settings in
   *Envoy Cloud Verification (Advanced)*: "Local battery stream" and "Stream heartbeat sensor" (no defaults; a home
   without a stream keeps today's behaviour). Freshness ships in the fail-closed mode (`DEFAULT_SOC_STREAM_MAX_AGE_S
   = 0`: the heartbeat sensor is required); the D0-S1 measurement picks the final rule.

## Knobs (all rung 1, module constants in `energy_const.py`)

| Constant | Value | Kill switch |
|---|---|---|
| `SOC_STREAM_TIER_ENABLED` | False | False = today's resolver |
| `DEFAULT_SOC_STREAM_MAX_AGE_S` | 0 | 0 = mode b (expire_after + mandatory heartbeat) |
| `DEFAULT_SOC_STREAM_COWITNESS_MAX_AGE_S` | 120 | — |
| `DEFAULT_SOC_STREAM_QUARANTINE_TICKS` | 2 | — |
| `DEFAULT_SOC_STREAM_COMPARE_MIN_SPACING_S` | 60 | — (R2-5) |
| `DEFAULT_ARB_RELEASE_UNTRUSTED_MAX_DEFER_MIN` | 60 | <= 0 = no release refusal (C1-3: decoupled from the blind-window guard) |
| `DEFAULT_SOC_UNTRUSTED_PAGE_LEAD_MIN` | 90 | <= 0 = never pages |
| `DEFAULT_SOC_UNTRUSTED_PAGE_DWELL_MIN` | 10 | 0 = page on first untrusted tick |

Config flow (rung 2): `energy_stream_battery_soc_entity`, `energy_stream_cowitness_entity`.
Persisted keys: `battery_soc_stream_trust`, `ec_untrusted_page_latch` (event-saved on change).

## Replay evidence (recorder, in-suite)

Fixture `quality/tests/fixtures/ec_degraded_data_p1_outages.json` (read-only recorder extract, 4 windows).
Fixture authority: on 10-01 05:44-07:59Z the real resolver reproduces the live `soc_source` at all 49 recorded
render points.

| Window | Observed in replay |
|---|---|
| 10-01 05:44-08:00Z | Releases after the 06:19:59 and 06:29:45 cloud ticks (live: EVs turned on at 06:20:09 and 06:30:22) are refused; the first trusted tick (06:39:35 envoy) releases. |
| 10-02 19:00-20:48Z | One page, at 20:30Z (15:30 CDT), "90 min before the 17:00" boundary. |
| 10-03 00:37-00:58 CDT | Stream unavailable → tier falls through cleanly (never read as 0); no page. |
| 10-03 16:00-17:28 CDT | Switch OFF: no page (untrusted < 10 min before 17:00); no cloud tick commands grid charge; 22:25Z cloud tick = 96.2 over-read. Switch ON: 22:05-22:25Z ticks all `stream` at 96/95/93/92/91, never the 96.2 cloud. |

## Live validation (prospective — replace with a `Validated <date>` table after restart)

- Attributes present after restart: `soc_tier_trusted`, `stream_trust=disabled`, `grid_charge_withheld_untrusted`,
  `arb_release_refused` on `sensor.ura_energy_coordinator_battery_strategy`.
- Next native outage without stream trust: `ura_activity_log` shows no `charger_on` from owner `arbitrage` while
  `soc_source` is not envoy/lkg/stream. Discriminator: a `charger_on` with `pause_owners=none` on an untrusted tick
  means D2a is not wired.
- Cloud-only tick during a latched charge (if one occurs): reason carries the withheld suffix and the cloud CFG
  switch goes `off` within one tick. Otherwise in-suite only.
- Untrusted window inside 90 min of a boundary (if one occurs): exactly one NM page. Otherwise in-suite only.
- Must-start-by held (if it occurs): NM + `anomaly_log` row type `ev_must_start_by_held`.

## Not done / deferred (plan completion)

- D0 A/B readout (§9) — runs 2026-10-05; gates flipping `SOC_STREAM_TIER_ENABLED` and the freshness rule.
- Pre-existing defect found, NOT fixed (outside the plan): `EnergyCoordinator._save_evse_state` references an
  unbound `_json` in the SOC-LKG and solar-LKG save blocks; the NameError is swallowed at DEBUG, so neither LKG is
  persisted today (the restore side works but never finds a row). Needs its own card.
- Storm-precharge non-degraded call site carries `cloud_withhold_exempt=True` but is behaviourally inert (that path
  only runs when the Envoy is fresh, so the tier is never `cloud_fallback` there).
