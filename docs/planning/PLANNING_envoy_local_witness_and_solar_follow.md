# Envoy local witness (MQTT livedata) — trust measurement, EC action upgrade, solar-follow upgrade

**Status:** planning · **Date:** 2026-09-25 · **Author:** orchestrator session
**Operator framing:** *"MQTT can be added as a trusted local witness. Just measure for its trust now
and then we decide."* — so nothing here builds until §3 returns numbers.

---

## 0. Answers to the direct questions

### 0.1 Is the cloud integration's rate 15 minutes? — NO, and this corrects me

I said "~15-min cadence cloud poll." **That was wrong.** Read from the integration's own source
(`/config/custom_components/enphase_ev/const.py`, HACS `barneyonline/ha-enphase-energy`, quality
scale *platinum*):

| Constant | Value |
|---|---|
| `DEFAULT_SCAN_INTERVAL` | **60** s |
| `DEFAULT_FAST_POLL_INTERVAL` / `MIN_FAST_POLL_INTERVAL` | 30 s |
| `DEFAULT_SLOW_POLL_INTERVAL` / `MIN_SLOW_POLL_INTERVAL` | 60 s |
| `MAX_POLL_INTERVAL` | 3600 s |
| Options keys | `OPT_FAST_POLL_INTERVAL`, `OPT_SLOW_POLL_INTERVAL` (options flow → menu: settings / devices / advanced / authentication_settings / …) |

And the per-endpoint cadence from its health payload: `battery_status` retries every **300 s**,
`battery_settings` / `current_power` / `grid_outage_context` every **60 s**.

**So the configured rate is 60 s, and SOC's own endpoint is 300 s — not 900 s.** But the OBSERVED
entity behaviour does not match either:

- `sensor.iq_battery_hacs_battery_overall_charge` went **86.0 @ 16:12:46 → 89.2 @ 16:34:46** — a
  **22-minute gap with no write at all**, during active charging when SOC was provably moving
  (the local stream showed 88 → 90 → 91 across that window).
- On every read, `last_changed == last_updated == last_reported` **exactly**. If the coordinator
  were writing the entity each poll, `last_reported` would advance independently. It never does.

**This is the finding, and it is not the same thing as "the cloud is slow."** Configured 60 s,
endpoint 300 s, observed ~15-22 min between entity writes. Something between the coordinator and the
entity is not propagating — candidates: the entity only writes on a change the coordinator itself
detects late, the `battery_status` family is in rate-limit backoff (its failure history shows
repeated **429 Too Many Requests** from Enlighten, each with ~1 h backoff), or the cloud's own
`battery_status` payload is refreshed slowly upstream.

**I am not going to guess which.** §3.4 measures it. Note the practical consequence either way:
**turning the poll interval down is the wrong lever** — the endpoint is already rate-limited by
Enphase, and polling harder risks pushing more families into 429 backoff, making freshness *worse*.

### 0.2 What is FREEDS? — irrelevant to us; leave it off

[FreeDS](https://github.com/pablozg/freeds) (freeds.es, by Pablo Zerón) is an open-source **solar
surplus diverter** — ESP32 + dimmer/relay hardware that routes excess PV into a resistive load,
typically a water heater, instead of exporting it.

The add-on's support for it is one line of plumbing: when `USE_FREEDS: true` it publishes a single
rounded grid-watts number to the hard-coded topic **`Inverter/GridWatts`** (source
`envoy_to_mqtt_json.py:79`, publish sites 326-328 / 368-370 / 404), which is the topic a FreeDS
device listens on.

**We have no FreeDS hardware, so `USE_FREEDS: false` is correct as configured.** Turning it on would
publish a second topic nothing consumes. (If we ever wanted a diverter — dumping surplus into the
water heater rather than exporting at the export rate — that is a *different* project, and URA's
load-shedding/EVSE machinery is the more natural home for it.)

---

## 1. Complete field inventory — what the stream actually carries

Captured from a live payload. **Every field is now bound to an entity** in
`/config/packages/envoy_mqtt.yaml` (25 entities: 23 sensors + 2 binary sensors), except the ones
explicitly marked *not captured* below.

### 1.1 Battery
| Field | Live value | Entity | Note |
|---|---|---|---|
| `meters.enc_agg_soc` | 91 | `sensor.envoy_live_battery_soc` | Encharge aggregate SOC |
| `meters.soc` | 91 | `sensor.envoy_live_soc_raw` | top-level SOC — **captured separately on purpose**, see §3.3 |
| `meters.enc_agg_energy` | 36450 Wh | `sensor.envoy_live_battery_energy` | |
| `meters.storage.agg_p_mw` | — | `sensor.envoy_live_battery_power` | −=charging, +=discharging |
| **`meters.backup_soc`** | **10** | `sensor.envoy_live_backup_reserve` | **LOCAL WITNESS FOR THE RESERVE SETTING — see §1.6** |
| `meters.backup_bat_mode` | 1 | `sensor.envoy_live_backup_battery_mode` | |
| `meters.acb_agg_soc` / `_energy` | 0 / 0 | `sensor.envoy_live_acb_soc` | AC Battery — none on site; captured so a future install isn't silently missed |

### 1.2 Power flows (each also has per-phase A/B and apparent power in the raw payload)
| Field | Entity |
|---|---|
| `meters.pv.agg_p_mw` | `sensor.envoy_live_solar_production` |
| `meters.grid.agg_p_mw` | `sensor.envoy_live_grid_power` (+=import, −=export) |
| `meters.load.agg_p_mw` | `sensor.envoy_live_house_load` |
| `meters.generator.agg_p_mw` | `sensor.envoy_live_generator_power` (0 — no generator) |
| `grid.agg_p_ph_a/b_mw` | `sensor.envoy_live_grid_power_l1` / `_l2` (live: +109 / −88 W) |
| `load.agg_p_ph_a/b_mw` | `sensor.envoy_live_house_load_l1` / `_l2` |

**Not captured (deliberate):** `agg_s_mva` apparent-power fields for all four meters, and the
per-phase apparent-power splits. They are real data but we have no consumer for VA, and each one is
another entity in the recorder. Trivial to add if a power-factor need appears.

### 1.3 Freshness — the trust instruments
| Field | Entity | Why it matters |
|---|---|---|
| **`meters.last_update`** (epoch) | `sensor.envoy_live_data_timestamp`, `sensor.envoy_live_data_age` (live: **25 s**) | **This is the correct freshness oracle.** MQTT arrival time only proves the ADD-ON is alive. `last_update` proves the ENVOY's data is moving. A frozen Envoy still answering HTTP would keep the add-on publishing happily forever while `last_update` stalled — that is the exact silent-staleness trap, and this field is the discriminator. |

### 1.4 System health
| Field | Live | Entity |
|---|---|---|
| `meters.main_relay_state` | 1 | `sensor.envoy_live_main_relay_state` + `binary_sensor.envoy_live_grid_connected` (**on**) — islanding / grid-connected, straight from the Envoy |
| `meters.gen_relay_state` | 5 | `sensor.envoy_live_generator_relay_state` |
| `meters.iqpm.total_PCU_count` | 48 | `sensor.envoy_live_microinverters_total` |
| `meters.iqpm.running_PCU_count` | 16 | `sensor.envoy_live_microinverters_running` — fleet health; 16/48 at dusk |
| `connection.sc_stream` | enabled | `sensor.envoy_live_stream_state` |
| `connection.auth_state` | ok | `sensor.envoy_live_auth_state` |
| `connection.mqtt_state` | connected | `binary_sensor.envoy_live_stream_publishing` |

**Not captured (deliberate):** `counters.*` (14 Envoy-internal counters — `MqttClient_publish`,
`rest_Status`, `SSL_Keys_Create` …), `tasks.*`, `connection.prov_state`, `meters.is_split_phase` / 
`phase_count` (static: 1 / 2), `dry_contacts` (empty on this site). These are debug telemetry with no
decision value; monotonic counters in the recorder are pure cost.

### 1.5 Config completeness — is anything missing from the add-on side?
Checked against the upstream settings table. Everything relevant is already correct:
`ENVOY_USE_HTTPS: true` (required — FW D8.3.6087 > D8.3.5286 dropped port 80), `BATTERY_INSTALLED:
true` (selects the `/ivp/livedata/status` path — the richest of the four the script offers),
`USE_FREEDS: false` (correct, §0.2), `DEBUG: false`. `ENVOY_PASSWORD` is an unused legacy field.

**There is no richer endpoint to switch to.** The script offers four modes — `livedata` (ours),
`production.json`, `/ivp/meters/readings`, `/stream/meter` — and `livedata` is the only one carrying
battery SOC, reserve, relay states and microinverter counts. We are already on the best one.

### 1.6 ⚠️ A correction I owe: MQTT **does** help reserve verification

I previously told the operator *"it does not help `reserve_write_verifiable()`."* **That was wrong,
and it was wrong because I reasoned from the README instead of reading a payload.**

`meters.backup_soc` is the **Envoy's own view of the backup reserve percentage** — currently **10**,
exactly matching `number.iq_battery_hacs_battery_reserve` = 10.0. That is precisely a *local witness
for a cloud-written setting*, which is the shape EC §2.6 (cloud-first write, local as witness) is
built around, and what the write-verify tripwire wants to compare against.

Today the local witness for reserve comes from the enphase_envoy integration, which is dark ~⅓ of the
day. `backup_soc` gives an independent 1 Hz witness that survives the pyenphase bug. **This may be
the single most valuable field in the payload after SOC**, and it was not on my earlier list.

---

## 2. Why this is worth doing — grounded in the EC design, not in urgency

Per `ENERGY_COORDINATOR_MANUAL.md` §2.5 (blind-hold contract) the EC resolves SOC through tiers, and
holds when none is fresh. Thresholds from `energy_const.py`:

| Tier | Max age | Status right now |
|---|---|---|
| `primary_envoy` | 300 s (`DEFAULT_BATTERY_SOC_PRIMARY_MAX_AGE_S`) | **dead** — pyenphase #181243 |
| `cloud_fallback` | 600 s (`DEFAULT_SOC_CLOUD_FALLBACK_MAX_AGE_S`) | alive but **870 s old** ⇒ expired |
| `lkg` | 300 s (`DEFAULT_SOC_LKG_MAX_AGE_S`) | 683 s ⇒ expired |
| **`tier`** | — | **`null` ⇒ TRUE BLIND, holding** |

Blind-hold is **safe, designed behaviour — not a bug.** The system is doing exactly what it should.
The problem is structural: *both* existing sources are disqualified, each for a different reason, and
no amount of threshold-tuning fixes that. Raising the 600 s bound would not make data fresher, it
would redefine stale as fresh — loosening a rung-1 safety constant to paper over a source gap.

**The gap is a fast LOCAL source.** MQTT livedata is the only candidate that is simultaneously fresh
enough (~1 s, three orders of magnitude inside the 300 s bar) and failure-independent of the bug.

**But note what this does NOT do**, so the cycle is not oversold:
- It does **not** fix the flapping — 2026.9.4 remains the cure.
- It does **not** touch control. Writes are cloud-first; local is witness-only (fw 8.3.x accepts-then-
  ignores local writes). Control never broke during outages and MQTT doesn't improve it.
- It carries **no lifetime energy counters**, so URA's grid-import / solar-export accumulators stay
  dependent on the flapping integration.

---

## 3. MEASURE FIRST — trust characterisation (the gate on everything below)

Per *Measure Before You Build*: **no deliverable in §4 or §5 is built until this returns numbers.**
The 25 entities are now in the recorder, so this is a read-only query over data that will exist,
not new instrumentation.

**Window:** ≥ 24 h from 2026-09-25 ~16:40 local, covering at least one full charge/discharge cycle,
one overnight, and (given ~110-160/day) many integration flap events.

### 3.1 Freshness — does it stay fresh?
`sensor.envoy_live_data_age` distribution: p50 / p95 / max, and total seconds above 60 s.
**Pass:** p95 ≤ 10 s AND max < 300 s (the primary-tier bar).
**Fail mode it catches:** the add-on republishing a frozen Envoy payload.

### 3.2 Independence — does it survive what kills the integration?
Cross-tabulate `sensor.envoy_live_battery_soc` availability against
`sensor.envoy_482543015950_battery` availability over the window.
**Pass:** MQTT available ≥ 99 % of the minutes in which the integration is `unavailable`.
**This is the whole value proposition and it must be measured, not assumed.**

### 3.3 Agreement — is it the same quantity? (Bug Class #63 guard)
Three comparisons, because near-equality in the common case can hide a concept split:
- `envoy_live_battery_soc` (`enc_agg_soc`) vs `envoy_live_soc_raw` (`soc`) — both read 91 now. If
  they NEVER diverge, one is redundant; if they diverge, we must know which the EC should trust.
- `envoy_live_battery_soc` vs `sensor.envoy_482543015950_battery` during windows where the
  integration is UP — the real apples-to-apples test.
- `envoy_live_battery_soc` vs cloud SOC — expected to differ by cloud lag, not by definition.

**Pass:** |MQTT − primary| ≤ 2 pp at p95 while both fresh, with **no systematic offset** (a constant
bias means different quantities, not noise).
**Discriminating detail:** cloud reports one decimal (89.2), MQTT reports integers (91). Confirm
that is rounding and not a different scale.

### 3.4 The cloud-cadence anomaly (§0.1)
Measure actual inter-write gaps for `sensor.iq_battery_hacs_battery_overall_charge` over 24 h:
p50 / p95 / max. **If p50 ≫ 300 s**, the cloud tier is structurally unable to meet its own 600 s
bound and that is a finding in its own right — it means the fallback tier is largely decorative and
the resolver has effectively been single-sourced onto a broken producer all along.

### 3.5 Self-consistency
`pv − (load + storage + grid)` residual over the window; p95 of |residual| as a fraction of load.
Held exactly on both spot checks (16:35: 5016 = 6913 + 1058 + 838 − ... balanced).
**Pass:** p95 residual < 2 % of load.

### 3.6 Contention — did we make the flapping worse?
Integration availability-transition count per day **before** (measured: 09-18 220, 09-19 324,
09-20 223, 09-24 ~246) vs **after** the add-on went live (2026-09-25 ~16:10).
**Fail:** a sustained rise beyond the 220-324 band ⇒ the ~1 Hz second client is contending, and we
throttle the add-on (`time.sleep(0.6)` is the knob) or reconsider.
**This is the hypothesis I refuted for the past and which only became testable today.**

### 3.7 Reserve witness
`sensor.envoy_live_backup_reserve` vs `number.iq_battery_hacs_battery_reserve` across a reserve
change. **Pass:** local witness converges to the cloud value, and the convergence LAG is recorded —
that lag is the calibration for any future write-verify use.

**Deliverable:** `docs/planning/AUDIT_envoy_mqtt_trust_measurement.md` with a row per criterion,
measured value, PASS/FAIL. Operator decides from that table.

---

## 4. Cycle A — EC action upgrade: MQTT as a third SOC tier + reserve witness

**Gated on §3.1-3.3, 3.5, 3.7 all PASS.**

**Tier: 2-DB minimum, likely Tier 3.** This adds a writer to the **SOC resolver**, a shared primitive
consumed by battery strategy, TOU, arbitrage and EVSE — the standing policy (CLAUDE.md) says
regression-prone work takes three framing-disjoint reviews, and the Tier-3 trigger *"threads a value
through a state machine consumed by many decision sites"* fits.

### The falsifiable invariant
> Under ANY combination of source availability, the EC never makes a battery decision on SOC data
> older than its tier's max-age bound, and never rates a source fresh on the basis of MQTT **arrival**
> time rather than the Envoy's **`last_update`**.

### Deliverables
- **A1 — Third resolver tier `local_stream`.** Slots between `primary_envoy` and `cloud_fallback`.
  Age computed from `meters.last_update`, **not** entity `last_updated` (that is the invariant's
  teeth — the add-on republishing a stale payload must NOT read as fresh).
  New constant `DEFAULT_SOC_LOCAL_STREAM_MAX_AGE_S` (rung 1, module constant — a safety bound, same
  class as its siblings, explicitly NOT an entity knob).
- **A2 — Config field** `energy_local_stream_battery_soc_entity` (CM scope), defaulting to
  `sensor.envoy_live_battery_soc`. *Prior-art check: mirrors the existing
  `energy_cloud_battery_soc_fallback_entity` pattern at `energy_const.py:305` — REUSE the shape, do
  not invent a new one.*
- **A3 — `soc_resolution` attribute extension:** add `local_stream_soc` + `local_stream_age_s`, and
  extend `tier` to emit `local_stream`. Keeps the existing observability contract (§4 of the manual)
  whole rather than bolting on a parallel one.
- **A4 — Reserve local witness.** Feed `sensor.envoy_live_backup_reserve` into the write-verify
  witness path alongside the existing local Envoy witness. **Scope fence: witness only.** It must
  NOT become a write path (§2.6 is explicit that local writes are accepted-then-ignored) and must not
  alter `is_reserve_verifiable()`'s three conditions (§2.5a) — that predicate is a documented
  emergency-backout surface and is out of scope.
- **A5 — Divergence detection becomes three-way.** Today `divergence_pp` is a 2-source comparison.
  With three sources we can identify *which* drifted rather than only that two disagree.

### Acceptance criteria
- **Verify:** with the integration `unavailable` and cloud > 600 s stale, `soc_resolution.tier` reads
  `local_stream` (not `null`) and the EC decides rather than blind-holds.
- **Verify:** stop the add-on → within `DEFAULT_SOC_LOCAL_STREAM_MAX_AGE_S` the tier demotes and,
  with no other fresh source, the EC returns to blind-hold. **Discriminating:** a stale-but-retained
  MQTT payload must produce demotion, NOT a confident wrong decision. This is the criterion that
  distinguishes the fix from a new failure.
- **Test:** mutation drill — neuter the `last_update`-based age computation so it falls back to
  entity `last_updated`; a specific test must go red.
- **Live:** post-restart, `soc_resolution` shows all three tiers with ages, and at least one
  genuine flap window resolves via `local_stream`.

### Non-goals
Control-path changes; anything touching `is_reserve_verifiable()`; replacing lifetime energy
counters; removing the cloud tier (it stays — three sources is the point).

---

## 5. Cycle B — solar-follow on a 1 Hz local grid reading

**Operator liked this one, and it turns out to be far cheaper than Cycle A.**

### Why it's cheap: the plumbing already exists
`energy_pool.py:4478-4479` — solar-follow already resolves its grid reading through a **two-tier
primary/fallback** pair of *configurable entities*:

```
_read_grid_watts() -> _read_one_grid(self._grid_primary)      # "primary"
                   -> _read_one_grid(self._grid_fallback)     # "fallback" / "primary_stale->fallback"
```

`_read_one_grid` is generic: any entity in W or kW, freshness from `last_reported` against
`SOLAR_FOLLOW_GRID_FRESH_S` (180 s), fail-closed on naive datetimes. And
`CONF_ENERGY_SOLAR_FOLLOW_GRID_FALLBACK_ENTITY` (`energy_const.py:1044`) already exposes the fallback
as an operator-settable field.

**So pointing solar-follow at `sensor.envoy_live_grid_power` may be a CONFIG CHANGE, not a build.**

### Why it's a real improvement
The 180 s threshold carries this comment in source: *"1.5x Emporia p90 (120s); tighter than 300
because a false-demote is a benign handoff to the fresher Envoy fallback."* The current primary is a
~120 s-p90 cloud/Emporia source. A **1 Hz local** grid reading is ~100× fresher on the exact signal
that decides how many amps to give the car — the quantity solar-follow is *literally regulating*.

Faster, more accurate excess-solar tracking means less grid import misattributed as surplus and less
lag chasing cloud transients — and per-phase L1/L2 is available too, which the current source cannot
give at all.

### Deliverables
- **B1 (config-only, do first):** set the solar-follow grid **fallback** to
  `sensor.envoy_live_grid_power`, leave primary alone. Zero code. Measure before/after: excess-solar
  decision latency, amps-change frequency, and how often `solar_follow_grid_source` reports
  `primary_stale->fallback`.
- **B2 (gated on B1 + §3):** promote it to **primary**, demoting the current source to fallback —
  only if B1 shows the local reading is at least as accurate and materially fresher.
- **B3 (only if B2 ships):** revisit `SOLAR_FOLLOW_GRID_FRESH_S`. It is sized for a 120 s-p90 source;
  with a 1 Hz primary a much tighter bound is defensible and would catch a stalled feed far sooner.
  **Do not touch it in B1/B2** — one variable at a time.

### Acceptance criteria
- **Sensor:** `solar_follow_grid_source` attribute reports the new source.
- **Verify:** during an excess-solar session, amps track a step change in export measurably sooner
  than the recorded baseline.
- **Verify (discriminating):** kill the add-on mid-session → solar-follow demotes to the other tier
  and does **not** strand the bay at stale amps. The `expire_after: 60` on the MQTT sensor makes it
  go `unavailable` rather than retain, which is exactly what `_read_one_grid` needs to fail closed.
- **Live:** one full session driven from the local source with no blind-handling entries.

### Tier
**B1 = Tier 1** (config-only, reversible, existing fallback slot, no code). **B2 = Tier 2**
(changes which source drives a live actuation path). **B3 = Tier 2-DB** (touches a tuned constant
with a documented sizing rationale).

---

## 6. Sequence

1. **§3 trust measurement** — 24 h, read-only. *(nothing builds before this)*
2. **B1** — config-only solar-follow fallback, immediately after §3.1/3.5 pass. Cheapest real win.
3. **Cycle A** — the EC resolver tier. Bigger, Tier 2-DB/3, needs the full §3 table.
4. **B2 / B3** — after A is live and the local source has a track record.

**Parked, with trigger:** the dual-homed / contention investigation — revive only if §3.6 shows the
flap rate rose after the add-on went live, or if flapping persists past 2026.9.4.

## 7. Open questions for the operator
- **Q1.** `enc_agg_soc` vs `soc` — if §3.3 shows they never diverge, drop `sensor.envoy_live_soc_raw`
  as redundant, or keep it as a cross-check? (Recommendation: keep — it costs one recorder row and it
  is the only free consistency check we have on the local source.)
- **Q2.** Does the cloud-cadence anomaly (§0.1/§3.4) warrant its own investigation? A cloud tier that
  writes every ~20 min cannot meet a 600 s bound, which would mean the resolver has been effectively
  single-sourced for some time.
- **Q3.** Appetite for the `backup_soc` reserve witness (A4) in the same cycle as the SOC tier, or
  split? (Recommendation: same cycle — same producer, same trust question, and splitting doubles the
  review cost for one shared measurement.)
