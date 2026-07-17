# HVAC Coordinator — Operator Manual

**Audience:** the homeowner running URA.
**Scope:** what the HVAC Coordinator (HC) does day to day, the knobs
you can turn, the surfaces you can watch, and how to intervene.
**Current through:** URA v5.18.0.

This is NOT a code walkthrough. For architecture see
`HVAC_COORDINATOR_DESIGN.md` (historical design spec).

---

## 1. What the HC actually does

The HC is the URA layer between many house rooms and the 3 Carrier
Infinity HVAC zones. Concretely it:

1. **Aggregates** room occupancy, temperature and humidity signals
   into per-HVAC-zone decisions.
2. **Chooses** between coarse control (preset changes:
   `home` / `away` / `sleep`) and fine control (setpoint offsets)
   depending on house state and the energy constraint published by the
   Energy Coordinator.
3. **Coordinates fans** in individual rooms as supplements when
   circulation matters (fan-noise mitigation and vacancy sweeps
   included).
4. **Applies vacancy behavior** — when a zone is empty long enough,
   ease off; when it's occupied too long without human input, log it.

The HC does NOT write setpoints for individual room thermostats in
Better Thermostat mode — it drives the Carrier zone thermostats.

---

## 2. House zones ≠ HVAC zones (architecture note)

This is a very common source of confusion — operator-corrected
2026-07-12:

- **HVAC zones** are the 3 Carrier Infinity zones keyed by the
  thermostat entity.
- **House zones** are the URA rooms/zones you configure per area.
- **One HVAC zone maps to MULTIPLE house zones by design.**

You will see compound names on the HVAC zone entities — e.g.
"Entertainment + Master Suite". That is the *legitimate* merge of the
house zones sharing an HVAC zone, NOT a bug or a stale config artifact.
Do not attempt to "fix" it by splitting one HVAC zone entity into two.
If you want independent control, add a Carrier zone.

---

## 3. How it decides (in plain language)

### 3.1 Presets and house state

The HC picks a Carrier preset based on the house state machine:

- **home** during normal occupied hours.
- **sleep** during the sleep window (protected — limited setpoint
  offsets are permitted here; big swings are not).
- **away** when the presence coordinator declares the house AWAY with
  confidence.

Energy Coordinator constraints (`normal / pre_cool / coast / shed`)
modulate WITHIN the chosen preset, mostly through setpoint offsets
(e.g. pre-cool -3°F for 2 hours before peak, then coast +3°F through
peak).

### 3.2 Vacancy management

When a zone's rooms all clear:

1. Start the **Zone Vacancy Delay** timer (see §4). If someone comes
   back inside the delay, cancel — no action.
2. If the delay expires, retreat toward energy-saving offsets and
   optionally sweep lights/fans off (governed by the vacancy-sweep
   switch).
3. The **Energy-Saving Zone Vacancy Delay** is a *shorter* version
   that fires when the Energy Coordinator publishes a shed/coast
   constraint — you want to give up on empty zones sooner when energy
   is expensive. It is bidirectionally clamped to be `<=` the normal
   delay (v4.7.25 review A-HIGH-1; confirmed live).

### 3.3 Occupancy protection

The **Max Zone Occupied Time** guard fires when a zone has been marked
occupied for longer than the configured hours without a state change
— that's a signal the presence detection may be stuck or the room's
genuinely been in continuous use and deserves a check. It surfaces as
a diagnostic, not an actuation.

### 3.4 Fan coordination (context)

- **v4.7.22 Mode-2 BLE-gated fan pause+recheck** — when mmwave might
  be seeing fan-wobble as motion, briefly pause the fan, recheck
  occupancy, then decide. High-still-risk guard protects nappers
  (bedroom rooms marked as such won't have their fans yanked during
  sleep). Master bedroom fan pause defaults SLEEP-only.
- Fan-noise mitigation Layer-1 (v4.7.20) is a silent, truth-preserving
  occupancy hold+decay — provenance-OR short-circuits first so
  mmwave-only signals get a confidence discount when a fan is running.

### 3.5 Sleep-state trust (v4.7.13, v4.7.14)

During SLEEP:
- Zone presence trust extends to any tracked person marked home
  (mmwave loses stationary bodies; person tracker is authoritative).
- Sleep-state fans in Master Bedroom run continuously through sleep
  (both fans validated 2026-06-05: ~7h uninterrupted despite
  occupancy signal bouncing, clean stop at wake).

---

## 4. Knobs and where they live

### 4.1 Number entities (dashboard-tunable, HVAC device)

| # | Entity | Default | What it does |
|---|---|---|---|
| 48 | `number.ura_hvac_coordinator_vacancy_grace` | (per config) | **Zone Vacancy Delay (minutes).** Time an empty zone must stay empty before the HC retreats. |
| 49 | `number.ura_hvac_coordinator_vacancy_grace_constrained` | (per config) | **Energy-Saving Zone Vacancy Delay (minutes).** Shorter delay used when the Energy Coordinator is shedding/coasting. **Clamped `<=` #48** (bidirectional). Confirmed live 2026-06-06: setting 49 → 30 while 48 = 15 clamps to 15. |
| 50 | `number.ura_hvac_coordinator_max_zone_occupied` | (per config) | **Max Zone Occupied Time (hours).** Diagnostic trip for "this zone has been occupied for suspiciously long". |

### 4.2 Button

| # | Entity | What it does |
|---|---|---|
| 51 | `button.ura_hvac_coordinator_reset_presence_timers` | **Reset Presence Timers.** Restores the 47–50 cluster to factory defaults in one options-save (single reload). Use this after experimentation. |

### 4.3 Switches

| # | Entity | What it does |
|---|---|---|
| 46 | `switch.ura_hvac_coordinator_vacancy_sweep_enabled` | **Vacancy Auto-Off.** When ON, vacancy sweeps turn lights/fans off after the delay. When OFF, they stay as-is (delay still runs, but no actuation). |
| — | Zone Intelligence master switch | When ON (default): per-zone vacancy management, duty cycle, presets by house state. When OFF: no zone-level intelligence — coarse manual mode. |

### 4.4 Options flow

- Carrier zone entity IDs and zone-to-room mappings.
- Comfort setpoint bounds per house state (home / sleep / away).
- Sleep window boundaries (also consumed by presence).
- Presence-timing cluster (persisted; live-attr-pushed — v4.7.25).

### 4.5 Reviewed constants

- Sleep-window offset limits (how much the energy coordinator can
  offset a setpoint during sleep).
- Fan-pause recheck intervals.
Live in `hvac_const.py`. Not dashboard knobs.

---

## 5. What to watch

- **Zone occupancy sensors** per HVAC zone: shows the aggregated
  answer for that zone.
- **Zone preset sensors**: current Carrier preset per zone
  (`home` / `sleep` / `away`).
- **Zone setpoint offset attributes**: how much the energy
  constraint is currently pulling the setpoint (e.g. `+3°F` during
  peak coast).
- **`sensor.<room>_unavailable_entities`**: tracks input sensors
  that went unavailable. NOTE — does NOT track dead actuators (light
  / fan / cover). See §6.
- **Vacancy-sweep counters**: `sweeps_today` attribute on the
  Vacancy Auto-Off switch shows how many sweeps fired today.

---

## 6. How to intervene safely

### 6.1 "The zone said 'away' with someone in it"

- Check the sleep/home boundary — was the house in `home_night`?
  The known Zone-1 gap: `home_night` vacancy override retreats when
  mmWave drops a still body (bed sensor is currently unused). Fix
  candidate is a Tier-1 extension of the sleep-state trust to
  `home_night`; not yet built.
- Check compound zone naming — the "away" was against the merged
  HVAC-zone entity, not a per-room state (see §2).

### 6.2 "The zone didn't do anything after the peak boundary"

- Check the Energy Coordinator's `current_holds_active` — an
  inclement `partial_hold` or arbitrage-completed HOLD legitimately
  pins battery reserve, not thermostat behavior. The HC still runs
  the coast offset.
- Check `sensor.<room>_unavailable_entities` — a dead mmwave will
  degrade a zone's confidence.

### 6.3 "The fan cycled all night in the bedroom"

Sleep-state trust was rolled out precisely for this (v4.7.13). If it
recurs:
- Verify the person tracker sees a home person during sleep.
- Verify Master Bedroom is flagged as high-still-risk (protects it
  from Mode-2 fan pause during sleep).

### 6.4 "A light/fan didn't turn off at exit"

**Check the actuator device state first, BEFORE blaming URA.** URA
detects occupancy fine but a `turn_off` call against an `unavailable`
device no-ops silently. `sensor.<room>_unavailable_entities` only
tracks input sensors, not actuators, so a dead light is invisible
there. Steps (also in project `CLAUDE.md` Troubleshooting):

1. Read the room's configured actuator entity from
   `.storage/core.config_entries` — verify which physical device the
   friendly name maps to (e.g. AV Closet light is
   `switch.switch_shelly1pmgen3_wifi_avcloset`, not
   `light.light01_light01`).
2. Check the actuator's live state; `unavailable` / `restored:true` =
   offline. Confirm via sibling power/voltage sensors.
3. Device offline ≠ integration failed. Reload only the specific
   stuck config entry; do NOT blanket-reload (blinks every working
   device).

### 6.5 Resetting presence timers

Button 51 (`button.ura_hvac_coordinator_reset_presence_timers`) is
the clean way — single options-save, single reload. Prefer it over
manually setting 48/49/50 back one by one.

---

## 7. Recent version history (for context)

| Version | What changed (operator-visible) |
|---|---|
| v4.7.13 | Sleep-state zone presence trust — mmwave-drop no longer forces away during sleep. Master bedroom fan validated ~7h continuous. |
| v4.7.14 | Away-state person-tracker veto — 33-min uninterrupted AWAY dwell post-fix vs 60–90s bouncing pre-fix. |
| v4.7.18.1 | Sleep→waking deadlock hotfix (raw-signal wake timer + daytime backstop). Organic wake confirmed. |
| v4.7.20 / .20.1 | Silent fan-interference occupancy hold+decay (Layer-1) + dispatcher import hotfix. |
| v4.7.22 | Mode-2 BLE-gated fan pause+recheck. High-still-risk guard protects bedroom nappers. |
| v4.7.24 | `OccupancySubstrate` per-room/per-kind raw layer beneath room + zone occupancy. Curated CONF sensor lists are single source of truth. |
| v4.7.25 | Presence-timer cluster surfaced as Number entities #48/49/50 + Reset button #51 + collapsed `presence_timing` config-flow section. Bidirectional clamp (#49 ≤ #48) confirmed live. Dwell Number persistence retrofit. |
| v4.7.29 | Day-boundary TOU mid_peak hold gated on peak-ahead (energy-side, but HC coast behavior downstream). |
