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

### 3.4b Override Arrester — manual-hold governance (with 2026-08-06 operator-immunity)

**Source of truth:** `custom_components/universal_room_automation/domain_coordinators/hvac_override.py`

**What the arrester does.** It watches every zone's climate entity for
manual thermostat holds — either an explicit switch to `preset_mode ==
"manual"`, or (on some Carrier/Bryant models) a setpoint touch that
induces the same. When it detects one, it computes the DELTA from what
URA "expected" (the setpoints active immediately before the hold),
classifies severity, and schedules a governance response:

| Severity | Trigger delta | Response | Code |
|---|---|---|---|
| **Severe** | `abs(delta) >= OVERRIDE_SEVERE_DELTA` (3°F, +1°F if energy-coast) | 2-min grace → revert preset | `_handle_severe_override` (hvac_override.py:~890) |
| **Normal** | `abs(delta) >= OVERRIDE_NORMAL_DELTA` (1°F, +1°F if energy-coast) | 5-min grace → 30-min compromise (halfway between hold and expected) → revert preset | `_handle_normal_override` (~940) + `_apply_compromise` (~1010) + `_revert_override` (~1100) |
| **Startup audit** | zone was in `manual` when HA (re)started | short grace → revert (in-memory timers were lost across the restart) | `async_startup_audit` (~485) |

Additionally, the same file owns the **AC-ramp soft-nudge**
(`_perform_soft_nudge`, ~1650) — a small `+°F` setpoint bump when a zone
has been "at setpoint but still burning kW" for the detection window.
The nudge is a corrective write against the operator's current
setpoint even when no `manual` preset is involved.

**Why this cycle happened (2026-08-06 livability gap).** The arrester was
designed to correct guest / child / accidental manual holds. In
practice it can ALSO shave the operator's own manual quick-cool during
a peak window (severe path reverts within 2 minutes; normal path
half-restores within 5). This behavior was **undocumented** and
routinely surprised the operator on hot afternoons — the "cool it
down NOW" quick-cool got half-taken-away by URA. The 2026-08-06 cycle
adds two governed exit ramps.

#### 3.4b.1 Person-scoped hold immunity (default: operator only)

When the arrester detects a manual hold, it now reads
`event.context.user_id` (the HA user who triggered the state change),
resolves it to a `person.*` entity, and checks whether that person is
on the operator-configured immune list (`Options → HVAC → Persons
whose holds are arrester-immune`; empty default falls back to the
first tracked person — the operator).

**If the user is immune:**
- The hold is stamped `immune=True` on an in-memory record keyed by
  zone_id (`OverrideArrester._immune_holds[zone_id]`).
- **No** grace timer is scheduled. **No** `_override_active[zone_id]`
  flag flips. **No** NM alert fires.
- Every subsequent shave path additionally consults
  `_corrective_writes_suppressed(zone_id)` as **defense-in-depth**:
  `_handle_severe_override`, `_handle_normal_override`,
  `_apply_compromise`, `_revert_override`, `async_startup_audit`, and
  the AC-ramp `_handle_overshoot_detected` dispatch all short-circuit
  with a `Arrester shave_skipped: zone=... path=... reason=immune_hold
  user=...` INFO ledger line.

**If the user is NOT resolvable or NOT listed** (physical thermostat
dial, guest, kid, unknown, or a person-lookup exception):
- Behavior is byte-identical to the pre-cycle arrester. Governance
  runs normally.
- This is the **fail-open direction**: uncertainty → governance (the
  safe default for the "someone we don't know did something" case).

**Sunset (first-of).** An immune hold is not permanent. It expires on
the first of:
1. A `SIGNAL_HOUSE_STATE_CHANGED` transition INTO a **durable house
   state** — `DURABLE_HOUSE_STATES = {"sleep", "away", "vacation"}`.
   Rationale: the operator's manual intent set 3h ago no longer
   reflects what they're currently doing if they've gone to sleep,
   left the house, or started a vacation.
2. The thermostat's own `next_activity` timestamp (schedule boundary)
   captured at stamp time.
3. `ARRESTER_IMMUNE_HOLD_MAX_S` (rung-1 module constant, default 4h)
   elapsed since the hold was stamped. A safety backstop for the
   "accidentally left in manual" case.

**Sunset does not force-clear the hold.** The manual preset and
elevated setpoint stay live on the thermostat. Sunset only removes
the `_immune_holds` record so the arrester's normal detection path
re-engages the next time the climate entity emits a state event. The
operator's setpoint is not clobbered by sunset — governance simply
regains jurisdiction going forward.

#### 3.4b.2 Temp Arrester Override switch (house-wide arrester suspension)

Entity: `switch.ura_hvac_temp_arrester_override` (HVAC
Coordinator device, `EntityCategory.CONFIG`).

**Default OFF.** When ON, **every** arrester corrective write is
suppressed house-wide (every zone, every path — severe, normal,
compromise, revert, startup audit, AC-ramp soft-nudge, AC-reset
escalation). Both axes route through the same
`_corrective_writes_suppressed` helper so no site can silently
forget one axis.

**Auto-sunset (first-of):**
1. `SIGNAL_HOUSE_STATE_CHANGED` transition INTO `sleep` — the "please
   leave me alone tonight" intent decays when the operator actually
   goes to sleep (sleep-preset schedule takes over).
2. `COMFORT_OVERRIDE_MAX_S` (rung-1, default 6h) elapsed since
   engagement — safety backstop for the "left it on" case.

On sunset the switch flips OFF and a **LOW** NM note fires:
`"Temp Arrester Override ended (auto)"`. The `suppressed_since` attribute
on the switch entity is available while ON for provenance.

**Intentional inversion: NOT restored across restart.** Unlike the
sibling HVAC switches (which default ON and restore OFF), Comfort
Override deliberately does not persist to `RestoreEntity`. Default-OFF
is the safe state — an accidental "leave it on" across an outage
should not persistently disable governance. The operator can always
re-engage after restart if intended.

#### 3.4b.3 Doctrine: durable-state context decay

The arrester's intent model is now: **an operator's manual intent
decays when the durable house-state context changes**. Two separate
axes (per-hold immunity, house-wide Temp Arrester Override) that share the
same sunset shape:
- Durable-state transition (context change).
- Hardware-supplied boundary (`next_activity` on the immune-hold axis
  only; the operator's own switch on the Comfort axis).
- Max-age safety backstop (a rung-1 module constant on each axis).

This mirrors CLAUDE.md's "state-machine × time seam" warning: **the
sunset is the seam.** All three trigger conditions are unit-tested;
each is bound to its effect by a semantic-binding assertion in
`quality/tests/test_arrester_operator_immunity.py` (see the mutation
table in the file docstring).

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
| — | `switch.ura_hvac_ac_ramp_master` | **AC Ramp-Down (Energy-Aware).** Default OFF (invasive feature — user opts in per zone). **Persistence (2026-08-06 fix):** the toggle write-through updates `entry.options[hvac_ac_ramp_master_enabled]`; the arrester seeds from this option at init so the setting SURVIVES config-entry reload. RestoreEntity is a belt-and-braces fallback for the fresh-install case only. |
| — | `switch.ura_hvac_temp_arrester_override` | **Temp Arrester Override** (2026-08-06). Default OFF. When ON, suspends **all** arrester corrective writes house-wide. Auto-sunsets on `sleep` transition OR `COMFORT_OVERRIDE_MAX_S` (6h) — flips OFF + LOW NM note. Does NOT restore ON across restart (default-OFF is safe). See §3.4b.2. |
| — | Zone Intelligence master switch | When ON (default): per-zone vacancy management, duty cycle, presets by house state. When OFF: no zone-level intelligence — coarse manual mode. |

### 4.4 Options flow

- Carrier zone entity IDs and zone-to-room mappings.
- Comfort setpoint bounds per house state (home / sleep / away).
- Sleep window boundaries (also consumed by presence).
- Presence-timing cluster (persisted; live-attr-pushed — v4.7.25).

| Persons whose holds are arrester-immune (2026-08-06) | `hvac_arrester_immune_persons` (person selector, multiple) | Person entities whose manual thermostat holds are IMMUNE to arrester compromise/revert and AC-ramp shaving (§3.4b.1). Empty default → resolved at runtime to the first tracked person (the operator). |

### 4.5 Reviewed constants

- Sleep-window offset limits (how much the energy coordinator can
  offset a setpoint during sleep).
- Fan-pause recheck intervals.
- **Arrester operator-immunity backstops (2026-08-06):**
  - `ARRESTER_IMMUNE_HOLD_MAX_S` — 4h. Safety cap on how long an
    operator's manual hold can bypass arrester governance. Rung-1
    (module constant): changing it changes the SAFETY envelope of
    the immunity feature.
  - `COMFORT_OVERRIDE_MAX_S` — 6h. Safety cap on how long Comfort
    Override can suspend house-wide corrective writes. Same rung
    rationale.
  - `DURABLE_HOUSE_STATES` — `{"sleep", "away", "vacation"}`.
    House states significant enough to sunset an earlier operator
    intent (§3.4b.3).
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
