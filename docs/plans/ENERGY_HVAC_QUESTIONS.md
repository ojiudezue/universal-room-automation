# Energy + HVAC Coordinator: Product Questions

**Context:** Reviewed ENERGY_COORDINATOR_DESIGN_v2.3.md, HVAC_COORDINATOR_DESIGN.md, PLANNING_v3.6.0_REVISED.md (C5/C6), and your in-scope features list. Questions are organized by domain, ranked by implementation-blocking priority.

---

## A. Scope & Phasing

### A1. Single coordinator or two?
The original plan has Energy as C5 and HVAC as C6 (separate cycles, separate files). Your in-scope list merges HVAC management into the Energy coordinator's "Actions" list. Which do you want?

- **(a)** One `EnergyCoordinator` that owns everything (TOU, battery, pool, EV, HVAC zones, fans)
- **(b)** Two coordinators as originally planned: `EnergyCoordinator` (TOU, battery, pool, EV, constraints) + `HVACCoordinator` (zones, presets, fans, responds to energy constraints)
- **(c)** One coordinator file but logically split (energy + HVAC in same file, HVAC section responds to energy signals internally)

My recommendation: (b) — clearer separation, testable independently, matches existing coordinator architecture. But your in-scope list suggests you may want (a) or (c) to reduce complexity.

### A2. Build order
If two coordinators, should we build Energy first (battery/pool/EV/TOU/forecast) and stub out HVAC constraints? Or do you want HVAC control first since it affects daily comfort, and backfill the energy intelligence later?

### A3. Vehicle detection — still deferred?
The v2.3 design marks vehicle detection as optional/future. Your in-scope list doesn't mention it. Confirm: skip vehicle detection for this cycle?

Answer - we may already have vehicle detection. Check presence coordinator

---

## B. TOU Rates & Billing

### B1. Rate source
Your in-scope list adds "Bill calculation" and "Bill prediction after a week." Where do TOU rates come from?

- **(a)** Hardcoded PEC rate table (summer/winter/shoulder as in v2.3 design) with manual update when rates change
- **(b)** User-configured via options flow (rate per period, season dates)
- **(c)** Pulled from an integration (which one?)

Answer - I gave this answer in chat. BTW I meant after a week into a billing cycle we should be able to predict the ending monthly bill

### B2. Bill cycle dates
You mention "Bill cycle dates." Is this:
- The billing period start/end dates (e.g., 15th to 14th)?
- Just for tracking "cost so far this billing cycle" vs "predicted total bill"?
- Do you have the actual PEC billing cycle dates, or do we need a config field?

Answer - Just date. My cycle begins on the 23 and 23rd of each month

### B3. Import vs export rate granularity
PEC has the same rate for import and export per period (per the v2.3 table). Is that still accurate, or are there separate net metering credits that differ from import rates? Some utilities have changed this.

Answer -  Its still the same but can. change. I don' think there is a symmetrical constraint.

---

## C. Forecasting & Prediction

### C1. Energy use prediction
You list "Energy use prediction vs actual adjustment." What is the prediction based on?

Answer - PV forecast and Weather forecast is the biggest prediction vectors. Energy use correlates with weather (temps primarily) and excess energy from PV and batteries correlate with how much can be stoed and exported. 
We can also use actual data from previous years as a way to sharpen the prediction using bayesan techniques.
There are sub predictions we can do:
- when will the batteries be full today (PV forecast and curve)?
- how much excess energy will we produce (PV forecast)?
- Will there by net export or import? How much? If no car is charged? if car is charged?
- will pre-cool be needed? How much energy do we expect to expend?
Not all are needed but we can do interesting things here


- **(a)** Historical consumption patterns (learn from past weeks, same day-of-week, similar weather)
- **(b)** Simple model: solar forecast - expected consumption = net position
- **(c)** Both — learned baseline + solar forecast + weather correlation

How granular? Per-hour? Per-TOU-period? Per-day?

Answer - both is likely the right answer. Per day is fine. At the begining of the day. 

### C2. Forecast accuracy evaluation
"Evaluate predictive accuracy" — is this:
- A diagnostic sensor showing forecast vs actual error?
- A feedback loop that adjusts future predictions based on past accuracy?
- Both?

Answer - Both. A diagnostic sensor showing forecast vs actual error. A feedback loop that adjusts future predictions based on past accuracy. We can assess prediction accuracy vs actual deviations and use this to adjust. A prediction accuracy sensor would be cool.

### C3. PV forecast source
Solcast is confirmed in the design. Is it the only PV forecast source, or do you also want to use Enphase's built-in production estimates as a cross-check?

Answer - Solcast is the only PV forecast source. Enphase does not have prediction only post production accumulation AFAIK. We have seveeral other forecast sources but solcast is teh most accurate

---

## D. SPAN Panel / Circuit Awareness

### D1. Circuit control scope
Your in-scope list says "Each circuit — measurement and control" with "Which circuits can be controlled and what cannot be." The v2.3 design mentions SPAN breaker control as emergency-only.

- How many SPAN circuits do you have total?
- Do you want a config flow where you tag each circuit as: controllable (auto-shed), measurement-only, or protected (never touch)?
- Or should we discover all SPAN circuits automatically and just let you mark the "never touch" list?

Answer - I have a few across 2 main panels. Each circuit can be monitored and controlled. These power the whole house and there are 2 sub panels. The main sub panel's main circuits are monitored by Emporia
Span has the information in it integration AFAIK. So you just need to discover it. 
We don't plan to control it. But we need to know we can. If the circuits are not marked in the integration, we can mark it after discovery

### D2. Smart plug loads
You mention "Optional — key controllable smart plug based loads ie L1 charger on a plug in the garage." How many of these exist today? Should they be configured in the energy config flow as "additional controllable loads," or are they just the EVSEs already mapped?

Answer - Additional controllable loads. The proper EVSE fall off SPAN and actually can be turned on or off at 2 places - the circuit and via the EVSE device - they are EMPORIA EVSEs    

### D3. Circuit anomaly: "energy goes away"
You mention detecting when "energy goes away from a circuit, tripped?" This implies monitoring for sudden zero-power on a circuit that should have load. Is this:
- A notification only (via NM)?
- An automatic action (attempt breaker re-enable via SPAN)?
- Just logging for awareness?

Answer - A critical notification via NM. Tripped breakers cannot be fixed in software in SPAN. Only software turned off can be turned back on in software. For the sub panels, off on in software is not an option.
Loggind and sensor would be ideal too so it can be programmed in other ways via automation

---

## E. HVAC Control Details

### E1. AC Reset behavior
You describe "Reset — Stop/Start AC based on temperature threshold reached but still cooling/heating long after temp is reached." Clarify the trigger:

- The thermostat has reached setpoint but `hvac_action` is still `cooling`/`heating` for X minutes past reaching target?

Answer - Yes this is the use case

- What's the threshold? e.g., current_temp is at or below target_temp_high for 10+ minutes but system still actively cooling?

Answer - Configurable. With a good default. Say 10 minutes to allow the HVAC to adjust automatically itself or not. Somesimes it seems stuck

- Is the reset action: set `hvac_mode` to `off`, wait N seconds, set back to `heat_cool`? Or cycle through `fan_only` first?

Answer - the former has worked for me. I recommend it

- Is this a Carrier Infinity quirk you've observed, or a general safeguard?

Answer - likely a quirk but maybe you can research this to see if its generalized. It feels like it could be.

### E2. HVAC mode: always on Auto (heat_cool)?
You say "Always on Auto — heat_cool." Does this mean:
- Never programmatically switch to `cool` or `heat` mode — always use `heat_cool`?

Answer - I prefer this so the system can adjust itself as intended. There has to be a good reason to do sth different

- Or is this the default, but energy coordinator can switch to `cool`-only during summer to prevent unnecessary heating cycles?

Answer - We should reserve the right but in the summer, the threshold is always at the upper end and there is almost never a risk of heating at all.

### E3. Preset mode as primary lever
You say "Adjust Preset mode first. Edit preset ranges next. Set to temp level only as last resort." The HVAC design doc has the same philosophy (coarse → fine → hybrid). Confirm this priority order is still correct:

Answer - confirmed

1. Change `preset_mode` (home/away/sleep) based on house state
2. Adjust preset temp ranges (target_temp_high/low offsets) for energy optimization
3. Direct temp setpoint control only for pre-cool/coast scenarios

### E4. Comfort curtailment — "feeling comfort"
You mention "Adjust temp levels automatically based on occupancy and feeling comfort." What is "feeling comfort"?


- Is this the livability score from the design doc (0-10 scale)?
- Or do you want actual occupant feedback (e.g., someone taps "too hot" / "too cold" on a dashboard)?
- Or is it purely derived from sensor data (temp delta from setpoint + humidity)?

Answer - made feeling comfort up. How people feel is usually a combination of temp, humidity and external temp delta vs simple temp. We should find research that helps us understand how bet to adjust for livability. Its probably edge case. Coarse strategies will satisy the pareto principle.

### E5. Carrier-specific awareness
You mention "Awareness of system capabilities ie Bryant/Carrier." What specifically needs to be Carrier-aware beyond what the `climate` entity already exposes?

- Minimum compressor cycle time (prevent short-cycling)?
- Knowledge of the Infinity system's built-in scheduling?
- Awareness that preset changes take effect gradually (not instant)?

Answer - yes all those things. Can be found in the model manual probably

---

## F. Presence-Driven HVAC

### F1. Room vs zone vs house presence
You say HVAC should "React to room, zone and house presence." The HVAC design maps URA rooms → HVAC zones. But what are the specific behaviors?

- **Room vacant, zone occupied:** Keep conditioning (other rooms in zone are occupied)

Answer - yes

- **Zone vacant, house occupied:** Switch to `away` preset for that zone?

Answer - yes

- **House vacant (AWAY state):** All zones to `away` or `vacation` preset?

Answer - Yes

- **Arriving:** Pre-condition on arrival detection?

Answer - yes. If and only if the daily energy budget is fat enough and we can maximize grid exports properly. Cost saving is a major priority.

### F2. Conflict: Energy constraint vs presence comfort
If Energy says "coast +3°F" but someone just walked into a 78°F room (setpoint 74), does presence override the energy constraint? Or does energy always win during peak TOU? What's the hierarchy?

Cost saving first
Comfort next
If comfort is way off to the point where human will manually intervene, best to run a cool short comfort conditioning cycle and then return to saving priorities. We should pre-cool when we can to prevent this situation as often as possible.

---

## G. Platform Integration Specifics

### G1. Generator monitoring
You list "Generator (Generic)." What generator entities exist in HA today? Is this just monitoring (is it running? fuel level?) or do you want automated load management during outages?

Answer - A generac 22kw air cooled. Its just monitoring. Not much use except for state monitoring and alerts.

### G2. Blinds / Hunter Douglas
You list "Blinds optional (Hunter Douglas)." Is this about:
- Closing blinds during peak solar gain to reduce cooling load?

Answer - Yes

- Integrating with the existing cover automation (v3.6.39)?

Answer - Not really. Center the common area covers vs room covers.

- A separate energy-driven cover strategy (e.g., close south-facing blinds at 2pm in summer)?

If so, which covers are south/west-facing and relevant for solar gain? Or should we just use the existing room cover config?

Answer - We should specify common area covers to handle this used case

### G3. Emporia vs SPAN
Both Emporia (EVSEs) and SPAN (panel) are listed. Are there Emporia energy monitors on circuits beyond the EVSEs, or is SPAN the sole circuit-level monitor?

SPAN - every circuit in house
Emporia - EVSEs, Excess solar monitoring, Sub panel monitoring (sub panel is fed from SPAN paanel so can be entirely isolated if necessary)

---

## H. Sensors & Observability

### H1. Bill prediction sensor
You want "Bill prediction after a week." Is this:
- `sensor.ura_energy_predicted_bill` — extrapolates current billing cycle consumption to end-of-cycle cost?
- Updates daily after accumulating a week of data?
- Needs to know billing cycle dates (see B2)?

Answer - Exactly. Update daily after a week of accumulation. You already have the billing cycle info

### H2. Cost tracking granularity
Beyond predicted bill, do you want:
- Real-time cost rate (current $/kWh based on TOU period)?
- Cost today / cost this week / cost this billing cycle?
- Import cost vs export credits separated?

Answer - yes to all

---

## I. Implementation Constraints

### I1. Decision cycle frequency
The v2.3 design says "every 5 minutes + on TOU transitions + on significant changes." Your in-scope list doesn't override this. Confirm 5-minute base cycle is acceptable?

Answer - This seems fine.

### I2. Config flow complexity
Energy + HVAC will need substantial config. The current coordinator manager config flow handles enable/disable toggles. Options for the energy config:

- **(a)** Single long config step (like room setup) with all energy settings
- **(b)** Multi-step wizard: TOU rates → Battery → Pool → EVSEs → HVAC zones → Circuits
- **(c)** Minimal config at setup, most settings in options flow (reconfig)

Answer - number 3.

### I3. Load shedding priority
The v2.3 design lists a default priority: pool speed → EV pause → infinity edge → pool heater → HVAC setback → circuits. Is this still correct? Should it be user-configurable in the options flow?

Load shedding is high risk. It should be off by default. We should plan it and stub it out. It should not be user configurable initially

---

## Answers (from Oji)

### A1: Two coordinators
Two separate coordinators. Energy (priority 40) owns battery/pool/EV/SPAN/TOU.
HVAC (priority 30) owns climate zones and zone fans. Energy publishes constraints
via dispatcher signal, HVAC responds. Follows existing MECE + priority architecture.

### A2: Energy first
Build Energy coordinator first. It will take time to get right. HVAC comes after.
Stub out the constraint signal interface so HVAC can plug in later.

### B1: Rate source — RESOLVED
PEC TOU Interconnect rate captured in `docs/plans/TOU.md`. Three seasons
(summer Jun-Sep, shoulder Mar/Apr/May/Oct/Nov, winter Dec-Feb). Import and
export rates are symmetric. Off-peak is flat $0.043481 all seasons.
Summer has 3 tiers (off/mid/peak), shoulder and winter have 2 (off/mid).
Fixed charges: $32.50 service + $0.0225 delivery + $0.0199 transmission per kWh delivered.

Will ship as a YAML/dict default with UI override option for rate changes.

---

## TOU Rate Representation Options

Oji will provide a PEC rate file. Here are the options for how to consume it:

| Option | How It Works | Pros | Cons |
|--------|-------------|------|------|
| **A. YAML file** | `custom_components/.../rates/pec_2026.yaml` shipped with integration or in `/config/` | Simple, version-controlled, easy to read/edit | Manual update when rates change, no UI |
| **B. Config flow UI** | User enters rate per period + season dates in options flow | Self-service updates, no file management | Tedious to enter, error-prone, lots of fields |
| **C. Hybrid: file + UI override** | Ship default rate file, allow UI overrides for specific fields | Best of both, sensible defaults | More code to merge sources |
| **D. URL fetch** | Fetch rates from a public URL (utility API or static JSON hosted somewhere) | Auto-updating | PEC probably doesn't have an API; fragile dependency |
| **E. HA integration sensor** | Use an existing energy rate integration (e.g., `energy_tariff`, custom template sensors) | Leverages HA ecosystem | May not exist for PEC; adds external dependency |
| **F. Static Python dict** | Hardcode in `const.py` as a dict of season → period → rate | Zero config, fastest to implement | Locked to source code, requires deploy to update |

**Recommendation:** **Option C (file + UI override).**

- Ship a `rates.yaml` (or JSON) with the PEC 2026 schedule as default
- Load it on startup
- Options flow exposes key overrides: season dates, per-period rates
- When PEC changes rates (annually?), update the file in a release OR user overrides in UI
- Rate file format is simple enough to hand-edit if needed

Awaiting the rate file from Oji to finalize format.

---

## Summary: What I Need Most

| Priority | Question | Why It Blocks |
|----------|----------|---------------|
| ~~**P0**~~ | ~~A1: One or two coordinators~~ | **ANSWERED: Two** |
| ~~**P0**~~ | ~~A2: Build order~~ | **ANSWERED: Energy first** |
| ~~**P0**~~ | ~~B1: Rate source~~ | **ANSWERED: PEC TOU from docs/plans/TOU.md** |
| **P1** | D1: Circuit control scope | Config flow design |
| **P1** | E1: AC Reset specifics | Novel feature, needs exact behavior |
| **P1** | F2: Energy vs presence hierarchy | Conflict resolution logic |
| **P2** | B2: Bill cycle dates | Billing sensor design |
| **P2** | C1: Prediction model | Complexity scoping |
| **P2** | E4: Comfort definition | Livability scoring |
